"""Music stage: score candidates from ACE-Step 1.5 on Kaggle.

Every seed gives a different piece, so the stage works like a composer's
sketchbook: it generates one candidate per seed in music.seeds, a person
listens to them under the narration, and writes the index of the winner in
music.chosen with a reason. Assembly then uses that candidate.

This stage is allowed to fail. Without any candidate the assembly stage uses
a generated placeholder drone, and the quality check says so.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from .common import cache, config, runlog
from .providers import kaggle

STAGE = "music"
VERSION = 1
INFERENCE_STEPS = 8


def candidate_path(seed: int) -> Path:
    return config.OUTPUTS / "music" / f"cand_{seed}.wav"


def candidate_key(board: dict[str, Any], seed: int) -> str:
    music = board["music"]
    return cache.make_key(STAGE, VERSION, {
        "model": music["model"], "caption": music["caption"], "bpm": music["bpm"],
        "keyscale": music["keyscale"], "duration_s": music["duration_s"],
        "instrumental": music["instrumental"], "seed": seed, "inference_steps": INFERENCE_STEPS,
    })


def build_job(board: dict[str, Any], seeds: list[int], name: str) -> dict[str, Any]:
    music = board["music"]
    return {
        "name": name,
        "music": {
            "caption": music["caption"], "bpm": music["bpm"], "keyscale": music["keyscale"],
            "duration_s": music["duration_s"], "instrumental": music["instrumental"], "seeds": seeds,
        },
        "settings": {"config_path": music["model"], "inference_steps": INFERENCE_STEPS, "time_budget_min": 50},
    }


def log_job(outcome: dict[str, Any], board: dict[str, Any]) -> None:
    """Copy a finished Kaggle job into runs.jsonl: one line for the job, one per candidate."""
    results, music = outcome.get("results", {}), board["music"]
    environment = results.get("environment", {})
    runlog.write({
        "event": "remote_job", "stage": STAGE, "provider": "kaggle", "kaggle_ref": outcome.get("ref"),
        "status": outcome.get("status"), "wall_s": outcome.get("wall_s"),
        "remote_elapsed_s": results.get("elapsed_s"), "environment": environment,
        "notes": results.get("notes", []),
        "cost": {"unit": "gpu_session_seconds", "amount": results.get("elapsed_s"), "gpus": 2},
    })
    for task in results.get("tasks", []):
        runlog.write({
            "event": "model_call", "stage": STAGE, "shot": task.get("id"), "provider": "kaggle",
            "model": f"ACE-Step 1.5 ({music['model']})",
            "params": {"bpm": music["bpm"], "keyscale": music["keyscale"], "duration_s": music["duration_s"],
                       "instrumental": music["instrumental"], "inference_steps": INFERENCE_STEPS},
            "seed": task.get("seed"), "prompt": music["caption"],
            "status": task.get("status"), "error": task.get("error"), "latency_s": task.get("seconds"),
            "cost": {"unit": "gpu_seconds", "amount": task.get("seconds"), "gpu": environment.get("gpu")},
            "peak_vram_gb": task.get("peak_vram_gb"), "output": task.get("output"),
            "kaggle_ref": outcome.get("ref"),
        })


def run(board: dict[str, Any], manifest: cache.Manifest | None = None,
        force: set[str] | None = None) -> dict[str, list[str]]:
    """Generate the candidates that changed. Blocks until the Kaggle job finishes."""
    manifest = manifest or cache.Manifest()
    force = force or set()
    reused, generated, failed = [], [], []
    pending: list[int] = []

    for seed in board["music"]["seeds"]:
        name, path, key = f"cand_{seed}", candidate_path(seed), candidate_key(board, seed)
        if name not in force and (manifest.status(path, key) == "fresh" or manifest.restore(path, key, stage=STAGE, shot=name)):
            reused.append(name)
        else:
            pending.append(seed)

    note = None
    if pending and not kaggle.has_key():
        failed = [f"cand_{seed}" for seed in pending]
        note = "no Kaggle credentials: the film uses a placeholder drone until candidates exist"
        pending = []

    if pending:
        slug = f"heritage-music-{time.strftime('%m%d-%H%M')}"
        dest = config.JOBS / slug / "out"
        print(f"  {len(pending)} score candidate(s) to make in one Kaggle job")
        try:
            outcome = kaggle.run(slug, "music_job.py", build_job(board, pending, slug), dest, timeout_s=90 * 60)
        except Exception as exc:
            outcome = {"ref": slug, "status": "push_failed", "wall_s": 0, "results": {"notes": [str(exc)[:400]]}}
        log_job(outcome, board)
        done = {task.get("seed"): task for task in outcome.get("results", {}).get("tasks", [])}
        for seed in pending:
            name, produced = f"cand_{seed}", dest / f"cand_{seed}.wav"
            if done.get(seed, {}).get("status") == "ok" and produced.exists():
                candidate_path(seed).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(produced, candidate_path(seed))
                manifest.commit(candidate_path(seed), candidate_key(board, seed), stage=STAGE, shot=name)
                generated.append(name)
            else:
                failed.append(name)
                reason = done.get(seed, {}).get("error") or outcome.get("status")
                print(f"  {name}: no usable track ({reason})")

    if board["music"]["chosen"] is None and (reused or generated):
        print("  music.chosen is null: listen to the candidates, then set the index and a reason in storyboard.json")
    runlog.stage_summary(STAGE, reused=reused, generated=generated, failed=failed, note=note)
    return {"reused": reused, "generated": generated, "failed": failed}
