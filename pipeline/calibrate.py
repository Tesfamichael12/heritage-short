"""Experiment E7: measure Wan 2.2 TI2V-5B on Kaggle's T4 GPUs before queueing the film.

Nobody has published how long this model takes on a T4, and the T4 lacks the
number format the model prefers. So before spending the day's GPU time on a
batch, one small job answers:

- Does half precision produce a real picture, or black frames?
- How many seconds per denoising step at each size and length?
- How much GPU memory does each setting peak at?
- Is a larger square (crops to both formats) affordable next to a vertical clip?

Usage:
    python -m pipeline.calibrate [image.png]      (default: outputs/smoke/image.png)

Results land in outputs/experiments/E7_wan_calibration/ and every task is
logged to runs.jsonl with experiment_id E7.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image

from . import shots
from .common import config
from .providers import kaggle

EXPERIMENT = "E7"
MODEL = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
DEST = config.OUTPUTS / "experiments" / "E7_wan_calibration"
PROMPT = "The flame flickers gently, a soft breeze moves the curtain, the camera pushes in slowly"
NEGATIVE = (
    "blurry, low quality, distorted, deformed hands, extra fingers, text, subtitles, watermark, "
    "static, frozen frame, jerky motion, flicker"
)

# One change per row against the baseline (row 1). Two GPUs take alternate rows.
MATRIX = [
    {"id": "base_704sq_49f_20s", "width": 704, "height": 704, "num_frames": 49, "steps": 20},
    {"id": "frames_704sq_81f_20s", "width": 704, "height": 704, "num_frames": 81, "steps": 20},
    {"id": "size_960sq_49f_20s", "width": 960, "height": 960, "num_frames": 49, "steps": 20},
    {"id": "vertical_704x1280_49f_20s", "width": 704, "height": 1280, "num_frames": 49, "steps": 20},
    {"id": "steps_704sq_49f_10s", "width": 704, "height": 704, "num_frames": 49, "steps": 10},
    {"id": "small_512sq_49f_20s", "width": 512, "height": 512, "num_frames": 49, "steps": 20},
]


def small_jpeg(path: Path, side: int = 1024) -> bytes:
    """The input image, shrunk and compressed so it can travel inside the job script."""
    image = Image.open(path).convert("RGB")
    image.thumbnail((side, side), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


def build_job(image_path: Path, time_budget_min: int = 100) -> dict:
    import base64

    wanted = [r for r in os.environ.get("CALIBRATE_ROWS", "").split(",") if r]
    rows = [row for row in MATRIX if not wanted or row["id"] in wanted]
    tasks = [
        {**row, "image": "input.jpg", "prompt": PROMPT, "seed": 42, "guidance": 5.0, "precision": "fp16"}
        for row in rows
    ]
    return {
        "name": "wan-calibration",
        "inputs": [{"name": "input.jpg", "b64": base64.b64encode(small_jpeg(image_path)).decode("ascii")}],
        "tasks": tasks,
        "settings": {"model": MODEL, "negative_prompt": NEGATIVE, "time_budget_min": time_budget_min, "fps": 24},
    }


def report(outcome: dict) -> None:
    results = outcome["results"]
    print(f"\nKaggle job {outcome['ref']}: {outcome['status']} after {outcome['wall_s'] / 60:.1f} min")
    print(f"environment: {json.dumps(results.get('environment', {}))}")
    for note in results.get("notes", []):
        print(f"note: {note}")
    print(f"\n{'task':30s} {'status':8s} {'sec':>6s} {'s/step':>7s} {'VRAM GB':>8s}  check")
    for task in sorted(results.get("tasks", []), key=lambda t: t.get("id", "")):
        check = "black" if task.get("black") else "frozen" if task.get("frozen") else "picture ok"
        if task.get("status") not in ("ok", "black"):
            check = (task.get("error") or "")[:60]
        print(f"{task.get('id', '?'):30s} {task.get('status', '?'):8s} {task.get('seconds', 0) or 0:6.0f} "
              f"{task.get('seconds_per_step', 0) or 0:7.1f} {task.get('peak_vram_gb', 0) or 0:8.1f}  {check}")
    if results.get("fatal_traceback"):
        print("\nfatal error on Kaggle:\n" + results["fatal_traceback"][-1500:])


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    image = Path(argv[0]) if argv else config.OUTPUTS / "smoke" / "image.png"
    if not image.exists():
        print(f"No input image at {image}. Run `make smoke` first, or pass an image path.")
        return 1
    os.environ.setdefault("EXPERIMENT", EXPERIMENT)

    slug = f"heritage-wan-calibration-{time.strftime('%m%d-%H%M')}"
    dest = DEST / slug
    budget = int(os.environ.get("CALIBRATE_BUDGET_MIN", "100"))
    outcome = kaggle.run(slug, "wan_job.py", build_job(image, budget), dest, timeout_s=(budget + 40) * 60)
    shots.log_job(outcome, MODEL)
    (dest / "outcome.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    report(outcome)
    print(f"\nFiles: {config.rel(dest)}")
    return 0 if outcome["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
