"""Moving-shots stage: Wan 2.2 image-to-video on Kaggle's free T4 GPUs.

For every shot whose motion.mode is "wan", the keyframe plus a short motion
prompt becomes a clip of a few seconds. The work runs remotely:

    build a job  ->  push it to Kaggle  ->  wait  ->  download the clips

Shots go in small batches, most important first, at most two jobs at a time.
A Kaggle job cannot be watched while it runs and it is not documented whether
its outputs survive being killed, so a small batch limits what one failure
can cost.

This stage is allowed to fail. A shot without a clip is rendered by the
assembly stage as a slow pan and zoom over its keyframe, so the film is
always complete.

A clip's cache key includes the content hash of its keyframe: change the
keyframe and the clip is stale.
"""
from __future__ import annotations

import base64
import io
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image

from .common import cache, config, runlog
from .providers import kaggle

STAGE = "shots"
VERSION = 1
MAX_PARALLEL_JOBS = 2
DEFAULT_NEGATIVE = (
    "blurry, low quality, distorted, deformed hands, extra fingers, text, subtitles, watermark, "
    "static, frozen frame, jerky motion, flicker, morphing face"
)


def keyframe_path(shot_id: str) -> Path:
    return config.OUTPUTS / "keyframes" / f"{shot_id}.png"


def clip_path(shot_id: str) -> Path:
    return config.OUTPUTS / "shots" / f"{shot_id}.mp4"


def settings_of(board: dict[str, Any]) -> dict[str, Any]:
    video = board["video"]
    return {
        "model": video["model"],
        "width": video["width"], "height": video["height"], "num_frames": video["num_frames"],
        "steps": video["steps"], "guidance": video["guidance"],
        "precision": video.get("precision", "fp16"),
        "negative_prompt": video.get("negative_prompt", DEFAULT_NEGATIVE),
    }


def clip_key(board: dict[str, Any], shot: dict[str, Any]) -> str:
    framing = shot.get("framing", {})
    return cache.make_key(STAGE, VERSION, {
        **settings_of(board),
        "prompt": shot["motion"]["prompt"], "seed": shot["motion"]["seed"],
        "focus": [framing.get("focus_x", 0.5), framing.get("focus_y", 0.5)],
    }, {"keyframe": keyframe_path(shot["id"])})


def input_for(shot_id: str, side: int) -> dict[str, str]:
    """The keyframe, shrunk and compressed so it can travel inside the job script."""
    image = Image.open(keyframe_path(shot_id)).convert("RGB")
    image.thumbnail((side, side), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=92)
    return {"name": f"{shot_id}.jpg", "b64": base64.b64encode(buffer.getvalue()).decode("ascii")}


def task_for(board: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    settings, framing = settings_of(board), shot.get("framing", {})
    return {
        "id": shot["id"], "image": f"{shot['id']}.jpg",
        "prompt": shot["motion"]["prompt"], "seed": shot["motion"]["seed"],
        "width": settings["width"], "height": settings["height"], "num_frames": settings["num_frames"],
        "steps": settings["steps"], "guidance": settings["guidance"], "precision": settings["precision"],
        "focus_x": framing.get("focus_x", 0.5), "focus_y": framing.get("focus_y", 0.5),
    }


def build_job(board: dict[str, Any], batch: list[dict[str, Any]], name: str) -> dict[str, Any]:
    settings = settings_of(board)
    side = max(settings["width"], settings["height"])
    return {
        "name": name,
        "inputs": [input_for(shot["id"], side) for shot in batch],
        "tasks": [task_for(board, shot) for shot in batch],
        "settings": {
            "model": settings["model"], "negative_prompt": settings["negative_prompt"],
            "time_budget_min": board["video"].get("time_budget_min", 150), "fps": config.FPS,
        },
    }


def log_job(outcome: dict[str, Any], model: str, stage: str = STAGE) -> None:
    """Copy a finished Kaggle job into runs.jsonl: one line for the job, one per clip."""
    results = outcome.get("results", {})
    environment = results.get("environment", {})
    runlog.write({
        "event": "remote_job", "stage": stage, "provider": "kaggle", "kaggle_ref": outcome.get("ref"),
        "status": outcome.get("status"), "wall_s": outcome.get("wall_s"),
        "remote_elapsed_s": results.get("elapsed_s"), "environment": environment,
        "notes": results.get("notes", []),
        "cost": {"unit": "gpu_session_seconds", "amount": results.get("elapsed_s"),
                 "gpus": environment.get("gpu_count")},
    })
    for task in results.get("tasks", []):
        runlog.write({
            "event": "model_call", "stage": stage, "shot": task.get("id"), "provider": "kaggle", "model": model,
            "params": {k: task.get(k) for k in ("width", "height", "num_frames", "steps", "guidance", "precision")},
            "seed": task.get("seed"), "prompt": task.get("prompt"),
            "status": task.get("status"), "error": task.get("error"),
            "latency_s": task.get("seconds"),
            "cost": {"unit": "gpu_seconds", "amount": task.get("seconds"),
                     "gpu": (environment.get("gpus") or [None])[0]},
            "seconds_per_step": task.get("seconds_per_step"), "peak_vram_gb": task.get("peak_vram_gb"),
            "frame_check": {k: task.get(k) for k in ("black", "frozen", "mean", "std", "first_last_diff")},
            "output": task.get("output"), "kaggle_ref": outcome.get("ref"),
        })


def run(board: dict[str, Any], manifest: cache.Manifest | None = None,
        force: set[str] | None = None) -> dict[str, list[str]]:
    """Generate the clips that changed. Blocks until the Kaggle jobs finish."""
    manifest = manifest or cache.Manifest()
    force = force or set()
    reused, generated, failed, skipped = [], [], [], []
    pending: list[tuple[dict[str, Any], str]] = []

    for shot in board["shots"]:
        sid = shot["id"]
        if shot["motion"]["mode"] != "wan":
            continue
        if not keyframe_path(sid).exists():
            skipped.append(sid)
            continue
        key = clip_key(board, shot)
        path = clip_path(sid)
        if sid not in force and (manifest.status(path, key) == "fresh" or manifest.restore(path, key, stage=STAGE, shot=sid)):
            reused.append(sid)
            continue
        pending.append((shot, key))

    note = None
    if pending and not kaggle.has_key():
        failed = [shot["id"] for shot, _ in pending]
        note = "no Kaggle credentials: these shots use pan and zoom instead"
        pending = []

    if pending:
        pending.sort(key=lambda item: item[0]["motion"]["priority"])
        size = board["video"].get("batch_size", 3)
        batches = [pending[i:i + size] for i in range(0, len(pending), size)]
        stamp = time.strftime("%m%d-%H%M")
        model = board["video"]["model"]
        print(f"  {len(pending)} clip(s) to make in {len(batches)} Kaggle job(s), up to {MAX_PARALLEL_JOBS} at a time")

        def run_batch(index: int) -> tuple[list[tuple[dict[str, Any], str]], dict[str, Any], Path]:
            batch = batches[index]
            slug = f"heritage-shots-{stamp}-b{index + 1}"
            dest = config.JOBS / slug / "out"
            try:
                outcome = kaggle.run(slug, "wan_job.py", build_job(board, [s for s, _ in batch], slug), dest,
                                     timeout_s=(board["video"].get("time_budget_min", 150) + 45) * 60)
            except Exception as exc:
                outcome = {"ref": slug, "status": "push_failed", "wall_s": 0, "results": {"notes": [str(exc)[:400]]}}
            return batch, outcome, dest

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_JOBS) as pool:
            for batch, outcome, dest in pool.map(run_batch, range(len(batches))):
                log_job(outcome, model)
                done = {task.get("id"): task for task in outcome.get("results", {}).get("tasks", [])}
                for shot, key in batch:
                    sid, task = shot["id"], done.get(shot["id"], {})
                    produced = dest / f"{sid}.mp4"
                    if task.get("status") == "ok" and produced.exists():
                        clip_path(sid).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(produced, clip_path(sid))
                        manifest.commit(clip_path(sid), key, stage=STAGE, shot=sid)
                        generated.append(sid)
                    else:
                        failed.append(sid)
                        reason = task.get("error") or task.get("status") or outcome.get("status")
                        print(f"  {sid}: no usable clip ({reason}); it will use pan and zoom")

    if skipped:
        print(f"  skipped (no keyframe yet): {', '.join(skipped)}")
    runlog.stage_summary(STAGE, reused=reused, generated=generated, failed=failed, note=note)
    return {"reused": reused, "generated": generated, "failed": failed, "skipped": skipped}
