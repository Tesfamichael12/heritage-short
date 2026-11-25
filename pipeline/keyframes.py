"""Keyframe stage: the reference sheet first, then one still per shot.

The image model has no memory of the previous picture. Consistency comes from
what it is given every time: the same reference image, the same character
description and the same style block. So:

1. Each character gets one reference sheet image (outputs/refs/<id>.png).
2. Every keyframe that shows the character is conditioned on that sheet, and
   its prompt repeats the fixed description and the style block word for word.

Keyframes are square with the subject centred, so the vertical and the
horizontal film are both crops of the same image.

A keyframe's cache key includes the content hash of its reference sheet:
regenerate the sheet and every keyframe that used it becomes stale.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import cache, config, runlog
from .common.retry import MissingKey, QuotaExhausted
from .providers import cloudflare

STAGE = "keyframes"
VERSION = 1
SEED_STEP = 1000  # a failed attempt retries with seed + 1000, + 2000 ...


def sheet_path(character_id: str) -> Path:
    return config.OUTPUTS / "refs" / f"{character_id}.png"


def keyframe_path(shot_id: str) -> Path:
    return config.OUTPUTS / "keyframes" / f"{shot_id}.png"


def _style(board: dict[str, Any]) -> str:
    style = board["style"]
    parts = [style["style_block"].strip()]
    if style.get("negative", "").strip():
        parts.append(style["negative"].strip())
    return ". ".join(parts)


def sheet_prompt(board: dict[str, Any], character: dict[str, Any]) -> str:
    return f"{character['sheet_prompt'].strip()}. {character['description'].strip()}. {_style(board)}"


def shot_prompt(board: dict[str, Any], shot: dict[str, Any]) -> str:
    """The shot's own prompt, then the fixed character wording, then the fixed style block."""
    characters = {c["id"]: c for c in board["characters"]}
    parts = [shot["keyframe"]["prompt"].strip().rstrip(".")]
    for index, ref in enumerate(shot["keyframe"].get("characters", [])):
        parts.append(f"The person is the same person shown in image {index}: {characters[ref]['description'].strip()}")
    parts.append(_style(board))
    return ". ".join(parts)


def sheet_key(board: dict[str, Any], character: dict[str, Any]) -> str:
    settings = board["keyframes"]
    return cache.make_key("refs", VERSION, {
        "model": settings["model"], "size": settings["size"],
        "prompt": sheet_prompt(board, character), "seed": character["seed"],
    })


def shot_key(board: dict[str, Any], shot: dict[str, Any]) -> str:
    settings = board["keyframes"]
    references = {f"ref_{ref}": sheet_path(ref) for ref in shot["keyframe"].get("characters", [])}
    return cache.make_key(STAGE, VERSION, {
        "model": settings["model"], "size": settings["size"],
        "prompt": shot_prompt(board, shot), "seed": shot["keyframe"]["seed"],
    }, references)


def _generate(board: dict[str, Any], prompt: str, seed: int, references: list[Path],
              *, stage: str, shot: str | None, key: str) -> bytes:
    """One image. An error that is not a rate limit gets a new seed, up to max_attempts."""
    settings = board["keyframes"]
    attempts = settings.get("max_attempts", 3)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return cloudflare.generate_image(
                settings["model"], prompt, size=settings["size"], seed=seed + attempt * SEED_STEP,
                references=references, stage=stage, shot=shot, cache_key=key,
            )
        except (QuotaExhausted, MissingKey):
            raise
        except Exception as exc:  # for example a prompt the provider refuses
            last = exc
            print(f"  {shot or stage}: attempt {attempt + 1} of {attempts} failed: {str(exc)[:160]}")
    assert last is not None
    raise last


def run(board: dict[str, Any], manifest: cache.Manifest | None = None,
        force: set[str] | None = None) -> dict[str, list[str]]:
    """Generate the sheets and keyframes that changed. Returns what happened to each."""
    manifest = manifest or cache.Manifest()
    force = force or set()
    reused, generated, failed, stale_used = [], [], [], []
    stopped: str | None = None

    def produce(name: str, path: Path, key: str, prompt: str, seed: int, references: list[Path], stage: str) -> None:
        nonlocal stopped
        if name not in force:
            if manifest.status(path, key) == "fresh" or manifest.restore(path, key, stage=stage, shot=name):
                reused.append(name)
                return
        if stopped or not cloudflare.has_key():
            (stale_used if path.exists() else failed).append(name)
            return
        try:
            png = _generate(board, prompt, seed, references, stage=stage, shot=name, key=key)
        except QuotaExhausted as exc:
            stopped = str(exc)[:200]
            (stale_used if path.exists() else failed).append(name)
            return
        except Exception as exc:
            print(f"  {name}: gave up: {str(exc)[:200]}")
            (stale_used if path.exists() else failed).append(name)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        manifest.commit(path, key, stage=stage, shot=name)
        generated.append(name)

    # 1. Reference sheets. Their content feeds every keyframe's key, so they come first.
    for character in board["characters"]:
        produce(f"ref:{character['id']}", sheet_path(character["id"]), sheet_key(board, character),
                sheet_prompt(board, character), character["seed"], [], "refs")

    # 2. Keyframes, each conditioned on the sheets of the characters it shows.
    for shot in board["shots"]:
        references = [sheet_path(ref) for ref in shot["keyframe"].get("characters", [])]
        if any(not ref.exists() for ref in references):
            failed.append(shot["id"])
            print(f"  {shot['id']}: skipped, its reference sheet does not exist yet")
            continue
        produce(shot["id"], keyframe_path(shot["id"]), shot_key(board, shot), shot_prompt(board, shot),
                shot["keyframe"]["seed"], references, STAGE)

    note = None
    if stale_used:
        note = f"stale_used: {', '.join(stale_used)} (an older file was kept because no call could be made)"
        print(f"  WARNING {note}")
    if stopped:
        print("  Cloudflare's daily allowance is used up. It resets at 03:00 East Africa Time.")
    runlog.stage_summary(STAGE, reused=reused, generated=generated, failed=failed, note=note)
    return {"reused": reused, "generated": generated, "failed": failed, "stale_used": stale_used}
