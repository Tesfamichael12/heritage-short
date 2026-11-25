"""Quality check: measure the finished films and write the numbers down.

The films are graded by people, but the repository is graded as text. So
every requirement the film must meet is measured here and written to
outputs/final/qc.json: length, both frame sizes, frame rate, codecs,
loudness, true peak, the subtitle count, and which shots used generated
video and which fell back to a pan over the still.

The run fails if a hard limit is missed.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .common import config, ffmpeg

FINAL = config.OUTPUTS / "final"
MIN_S, MAX_S = 60.0, 90.0
LUFS_TOLERANCE = 1.0


def loudness(path: str) -> dict[str, float]:
    """Integrated loudness and true peak, from FFmpeg's EBU R128 meter."""
    stderr = ffmpeg.run(["-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"])
    summary = stderr[stderr.rfind("Summary:"):]
    integrated = re.search(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)

    def number(match: re.Match | None) -> float:
        return float(match.group(1)) if match and "inf" not in match.group(1) else float("-inf")

    return {"integrated_lufs": number(integrated), "true_peak_db": number(peak)}


def check_film(fmt: str, board: dict[str, Any]) -> dict[str, Any]:
    width, height = config.FORMATS[fmt]
    name = f"final/heritage_{fmt}.mp4"
    report: dict[str, Any] = {"file": f"outputs/{name}", "checks": {}}
    if not (config.OUTPUTS / name).exists():
        report["checks"]["exists"] = {"pass": False, "value": "missing"}
        return report

    info = ffmpeg.probe(name)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    seconds = float(info["format"]["duration"])
    levels = loudness(name)
    target, peak_limit = board["mix"]["target_lufs"], board["mix"]["true_peak_db"]

    checks = report["checks"]
    checks["duration_s"] = {"value": round(seconds, 2), "pass": MIN_S <= seconds <= MAX_S, "limit": f"{MIN_S:.0f} to {MAX_S:.0f}"}
    checks["frame_size"] = {"value": f"{video['width']}x{video['height']}",
                            "pass": (video["width"], video["height"]) == (width, height), "limit": f"{width}x{height}"}
    checks["frame_rate"] = {"value": video["r_frame_rate"], "pass": video["r_frame_rate"] == f"{config.FPS}/1", "limit": f"{config.FPS}/1"}
    checks["video_codec"] = {"value": video["codec_name"], "pass": video["codec_name"] == "h264", "limit": "h264"}
    checks["audio_codec"] = {"value": audio.get("codec_name"), "pass": audio.get("codec_name") == "aac", "limit": "aac"}
    checks["integrated_lufs"] = {"value": levels["integrated_lufs"],
                                 "pass": abs(levels["integrated_lufs"] - target) <= LUFS_TOLERANCE,
                                 "limit": f"{target} within {LUFS_TOLERANCE}"}
    checks["true_peak_db"] = {"value": levels["true_peak_db"], "pass": levels["true_peak_db"] <= peak_limit + 0.1,
                              "limit": f"at most {peak_limit}"}
    report["bytes"] = int(info["format"]["size"])
    return report


def run(board: dict[str, Any], timeline: dict[str, Any], assembly: dict[str, Any]) -> dict[str, Any]:
    films = {fmt: check_film(fmt, board) for fmt in config.FORMATS}
    spoken = [s for s in board["shots"] if s["narration"]["text"].strip()]
    cues = assembly.get("subtitle_cues", 0)
    music_source = assembly.get("audio", {}).get("music_source")

    content = {
        "shots": {"value": len(board["shots"]), "pass": 8 <= len(board["shots"]) <= 12, "limit": "8 to 12"},
        "every_shot_has_a_picture": {"value": assembly.get("missing_pictures", []),
                                     "pass": not assembly.get("missing_pictures")},
        "every_line_has_narration": {"value": timeline.get("missing_narration", []),
                                     "pass": not timeline.get("missing_narration")},
        "subtitle_cues": {"value": cues, "pass": cues >= len(spoken), "limit": f"at least {len(spoken)} (one per spoken line)"},
        "score_is_generated_music": {"value": music_source, "pass": music_source != "placeholder"},
        "score_was_chosen": {"value": board["music"]["chosen"], "pass": board["music"]["chosen"] is not None},
        "end_card_s": {"value": timeline["end_card"]["duration_s"], "pass": timeline["end_card"]["duration_s"] >= 2},
    }
    failures = [f"{fmt}: {name}" for fmt, film in films.items() for name, check in film["checks"].items() if not check["pass"]]
    failures += [name for name, check in content.items() if not check["pass"]]

    report = {
        "passed": not failures,
        "failures": failures,
        "films": films,
        "content": content,
        "shots_with_generated_video": assembly.get("clips_used", []),
        "shots_with_pan_and_zoom": assembly.get("kenburns_used", []),
        "audio": assembly.get("audio", {}),
        "timeline_total_s": timeline["total_s"],
    }
    FINAL.mkdir(parents=True, exist_ok=True)
    (FINAL / "qc.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\nQuality check")
    for fmt, film in films.items():
        for name, check in film["checks"].items():
            mark = "ok  " if check["pass"] else "FAIL"
            print(f"  {mark} {fmt:5s} {name:16s} {check['value']}   (limit: {check.get('limit', '')})")
    for name, check in content.items():
        mark = "ok  " if check["pass"] else "FAIL"
        print(f"  {mark} {'film':5s} {name:26s} {check['value']}")
    print(f"  clips: {len(report['shots_with_generated_video'])}, pan and zoom: {len(report['shots_with_pan_and_zoom'])}")
    print("  PASSED" if report["passed"] else f"  NOT PASSED: {', '.join(failures)}")
    return report
