"""Status: what is current, what is stale, what is missing, and today's call counts.

`make status` answers two questions before anything is spent:

1. If I ran `make film` now, what would regenerate?
2. How much of each provider's free allowance has this project used since
   that provider's last reset?
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import keyframes, music, narration, shots, validate
from .common import cache, runlog

GEMINI_RESET_UTC_HOUR = 8   # midnight Pacific, which is 11:00 East Africa Time
MARK = {"fresh": "ok", "stale": "STALE", "missing": "-"}


def _state(manifest: cache.Manifest, path, keys: list[str]) -> str:
    states = [manifest.status(path, key) for key in keys]
    if "fresh" in states:
        return "fresh"
    return "missing" if all(s == "missing" for s in states) else "stale"


def shot_rows(board: dict[str, Any], manifest: cache.Manifest) -> list[dict[str, str]]:
    rows = []
    for shot in board["shots"]:
        sid = shot["id"]
        row = {"shot": sid, "narration": "silent", "keyframe": "", "clip": "pan/zoom"}
        if shot["narration"]["text"].strip():
            keys = [narration.line_key(board, shot)]
            if board["narration"].get("fallback_model"):
                keys.append(narration.line_key(board, shot, board["narration"]["fallback_model"]))
            row["narration"] = _state(manifest, narration.line_path(sid), keys)
        references = [keyframes.sheet_path(ref) for ref in shot["keyframe"].get("characters", [])]
        if all(ref.exists() for ref in references):
            row["keyframe"] = manifest.status(keyframes.keyframe_path(sid), keyframes.shot_key(board, shot))
        else:
            row["keyframe"] = "missing"
        if shot["motion"]["mode"] == "wan":
            if keyframes.keyframe_path(sid).exists():
                row["clip"] = manifest.status(shots.clip_path(sid), shots.clip_key(board, shot))
            else:
                row["clip"] = "missing"
        rows.append(row)
    return rows


def last_reset(hour_utc: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    reset = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    return reset if reset <= now else reset - timedelta(days=1)


def usage(records: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """Calls and cost units since each provider's last reset."""
    now = now or datetime.now(timezone.utc)
    gemini_since = last_reset(GEMINI_RESET_UTC_HOUR, now)
    cloudflare_since = last_reset(0, now)
    week_start = (now - timedelta(days=(now.weekday() - 5) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)

    gemini: dict[str, int] = {}
    neurons, images, gpu_seconds = 0.0, 0, 0.0
    for record in records:
        try:
            when = datetime.fromisoformat(record["ts"])
        except (KeyError, ValueError):
            continue
        provider = record.get("provider")
        if record.get("event") == "model_call" and provider == "gemini" and when >= gemini_since:
            gemini[record.get("model", "?")] = gemini.get(record.get("model", "?"), 0) + 1
        if record.get("event") == "model_call" and provider == "cloudflare" and when >= cloudflare_since:
            if record.get("status") == "ok":
                images += 1
                neurons += float((record.get("cost") or {}).get("amount") or 0)
        if record.get("event") == "remote_job" and provider == "kaggle" and when >= week_start:
            gpu_seconds += float((record.get("cost") or {}).get("amount") or record.get("wall_s") or 0)
    return {
        "gemini_calls_since_reset": gemini,
        "cloudflare_images_today": images,
        "cloudflare_neurons_today_estimated": round(neurons, 1),
        "kaggle_gpu_session_minutes_this_week": round(gpu_seconds / 60, 1),
    }


def main() -> int:
    try:
        board = validate.load()
    except validate.StoryboardError as exc:
        print("storyboard.json is not valid:")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1

    manifest = cache.Manifest()
    print(f"{'shot':6s}{'narration':12s}{'keyframe':12s}{'clip':12s}")
    would_run = []
    for row in shot_rows(board, manifest):
        cells = [MARK.get(row[name], row[name]) for name in ("narration", "keyframe", "clip")]
        print(f"{row['shot']:6s}{cells[0]:12s}{cells[1]:12s}{cells[2]:12s}")
        would_run += [f"{name}:{row['shot']}" for name in ("narration", "keyframe", "clip")
                      if row[name] in ("stale", "missing")]

    print()
    for character in board["characters"]:
        state = manifest.status(keyframes.sheet_path(character["id"]), keyframes.sheet_key(board, character))
        print(f"reference sheet {character['id']}: {MARK[state]}")
        if state != "fresh":
            would_run.append(f"ref:{character['id']}")
    for index, seed in enumerate(board["music"]["seeds"]):
        state = manifest.status(music.candidate_path(seed), music.candidate_key(board, seed))
        chosen = "  <- chosen" if board["music"]["chosen"] == index else ""
        print(f"score candidate {index} (seed {seed}): {MARK[state]}{chosen}")
        if state != "fresh":
            would_run.append(f"music:cand_{seed}")

    print()
    if would_run:
        print(f"`make film` would generate {len(would_run)} output(s): {', '.join(would_run)}")
    else:
        print("Everything is current. `make film` would call no model.")

    used = usage(runlog.read())
    print("\nFree allowance used by this project since each provider's last reset:")
    calls = used["gemini_calls_since_reset"]
    print("  Gemini (resets 11:00 EAT): " + (", ".join(f"{m} x{n}" for m, n in sorted(calls.items())) or "no calls"))
    print(f"  Cloudflare (resets 03:00 EAT): {used['cloudflare_images_today']} images, "
          f"about {used['cloudflare_neurons_today_estimated']:.0f} of 10,000 neurons")
    print(f"  Kaggle (weekly): {used['kaggle_gpu_session_minutes_this_week']:.0f} GPU session minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
