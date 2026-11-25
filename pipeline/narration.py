"""Narration stage: one speech call per shot, then the timeline.

Each line is generated as its own file, so changing one line costs one call.
The stage then measures every line and writes outputs/timeline.json, where a
shot lasts as long as its narration needs or its planned length, whichever is
longer. The narration sets the cut.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

from .common import cache, config, runlog
from .common.retry import MissingKey, QuotaExhausted
from .providers import gemini

STAGE = "narration"
VERSION = 1
MIN_FILM_S, MAX_FILM_S = 60.0, 90.0


def line_path(shot_id: str) -> Path:
    return config.OUTPUTS / "narration" / f"{shot_id}.wav"


def line_key(board: dict[str, Any], shot: dict[str, Any], model: str | None = None) -> str:
    narration = board["narration"]
    return cache.make_key(STAGE, VERSION, {
        "model": model or narration["model"],
        "voice": narration["voice"],
        "style_instruction": narration["style_instruction"],
        "text": shot["narration"]["text"],
    })


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def frames_for(seconds: float) -> int:
    """Whole frames at the film's frame rate, rounded up so nothing is cut off."""
    return int(-(-seconds * config.FPS // 1))


def build_timeline(board: dict[str, Any], measured: dict[str, float]) -> dict[str, Any]:
    """Shot lengths from the measured narration. Pure arithmetic, no I/O."""
    narration = board["narration"]
    lead_in = narration.get("lead_in_s", 0.4)
    tail = narration.get("tail_s", 0.6)

    shots, frame_cursor = [], 0
    for shot in board["shots"]:
        spoken = measured.get(shot["id"], 0.0)
        needed = lead_in + spoken + tail if spoken else 0.0
        frames = frames_for(max(shot["duration_s"], needed))
        start = frame_cursor / config.FPS
        shots.append({
            "id": shot["id"],
            "start_s": round(start, 4),
            "duration_s": round(frames / config.FPS, 4),
            "frames": frames,
            "planned_s": shot["duration_s"],
            "narration_s": round(spoken, 3),
            "narration_start_s": round(start + lead_in, 4) if spoken else None,
            "stretched": needed > shot["duration_s"],
        })
        frame_cursor += frames

    card_frames = frames_for(board["end_card"]["duration_s"])
    total_frames = frame_cursor + card_frames
    return {
        "fps": config.FPS,
        "shots": shots,
        "end_card": {
            "start_s": round(frame_cursor / config.FPS, 4),
            "duration_s": round(card_frames / config.FPS, 4),
            "frames": card_frames,
        },
        "total_frames": total_frames,
        "total_s": round(total_frames / config.FPS, 4),
    }


def timeline_problem(timeline: dict[str, Any]) -> str | None:
    total = timeline["total_s"]
    if MIN_FILM_S <= total <= MAX_FILM_S:
        return None
    longest = sorted(timeline["shots"], key=lambda s: s["narration_s"], reverse=True)[:3]
    names = ", ".join(f"{s['id']} ({s['narration_s']:.1f}s)" for s in longest)
    direction = "Shorten" if total > MAX_FILM_S else "Lengthen"
    return (f"the film would run {total:.1f}s; it must be {MIN_FILM_S:.0f} to {MAX_FILM_S:.0f}s. "
            f"{direction} the narration. Longest lines: {names}")


def _generate(board: dict[str, Any], shot: dict[str, Any], manifest: cache.Manifest) -> None:
    """One line, trying the fallback model if the main one is out of quota."""
    narration = board["narration"]
    models = [narration["model"]]
    if narration.get("fallback_model"):
        models.append(narration["fallback_model"])

    last: Exception | None = None
    for model in models:
        key = line_key(board, shot, model)
        try:
            wav = gemini.synthesize(
                model, shot["narration"]["text"], voice=narration["voice"],
                style_instruction=narration["style_instruction"],
                stage=STAGE, shot=shot["id"], cache_key=key,
            )
        except QuotaExhausted as exc:
            last = exc
            print(f"  {shot['id']}: {model} is out of quota for today")
            continue
        path = line_path(shot["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav)
        manifest.commit(path, key, stage=STAGE, shot=shot["id"])
        return
    assert last is not None
    raise last


def run(board: dict[str, Any], manifest: cache.Manifest | None = None,
        force: set[str] | None = None) -> dict[str, Any]:
    """Generate what changed, then write and return the timeline."""
    manifest = manifest or cache.Manifest()
    force = force or set()
    reused, generated, failed, stale_used = [], [], [], []
    quota_gone = False

    for shot in board["shots"]:
        sid = shot["id"]
        if not shot["narration"]["text"].strip():
            continue
        path = line_path(sid)
        keys = [line_key(board, shot)]
        if board["narration"].get("fallback_model"):
            keys.append(line_key(board, shot, board["narration"]["fallback_model"]))

        if sid not in force:
            if any(manifest.status(path, key) == "fresh" for key in keys):
                reused.append(sid)
                continue
            if any(manifest.restore(path, key, stage=STAGE, shot=sid) for key in keys):
                reused.append(sid)
                continue

        if quota_gone or not gemini.has_key():
            (stale_used if path.exists() else failed).append(sid)
            continue
        try:
            _generate(board, shot, manifest)
            generated.append(sid)
        except QuotaExhausted:
            quota_gone = True
            (stale_used if path.exists() else failed).append(sid)
        except MissingKey:
            (stale_used if path.exists() else failed).append(sid)

    note = None
    if stale_used:
        note = f"stale_used: {', '.join(stale_used)} (an older file was kept because no call could be made)"
        print(f"  WARNING {note}")
    if quota_gone:
        print("  The speech quota is used up for today. It resets at 11:00 East Africa Time.")
    runlog.stage_summary(STAGE, reused=reused, generated=generated, failed=failed, note=note)

    measured = {
        shot["id"]: wav_seconds(line_path(shot["id"]))
        for shot in board["shots"] if line_path(shot["id"]).exists() and shot["narration"]["text"].strip()
    }
    timeline = build_timeline(board, measured)
    timeline["missing_narration"] = failed
    config.TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    config.TIMELINE.write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")
    return timeline
