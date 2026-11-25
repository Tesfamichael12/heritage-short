"""Kaggle as a remote GPU: push a script, wait for it, download what it made.

The remote scripts in pipeline/remote/ are written to stand alone. `build_job`
puts the job description (inputs, tasks, settings) at the top of a copy of the
script as a JSON string, so the file Kaggle runs is fully self-describing.

A Kaggle job is a batch run: nothing can be seen while it runs, and it is not
documented whether outputs survive a job that is killed. The remote scripts
therefore never crash on purpose. They catch each task's error, respect a time
budget and always finish with a results.json.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..common import config
from ..common.retry import MissingKey

ACCELERATOR = "NvidiaTeslaT4"  # Kaggle's name for "GPU T4 x2"
REMOTE = Path(__file__).resolve().parents[1] / "remote"
FINAL = ("complete", "error", "cancel")


def has_key() -> bool:
    token = config.env("KAGGLE_API_TOKEN") or (config.env("KAGGLE_USERNAME") and config.env("KAGGLE_KEY"))
    return bool(token and config.env("KAGGLE_USERNAME"))


def username() -> str:
    name = config.env("KAGGLE_USERNAME")
    if not name:
        raise MissingKey("KAGGLE_USERNAME is not set in .env")
    return name


def cli(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    """Run the Kaggle command-line tool from this project's environment."""
    if not has_key():
        raise MissingKey("KAGGLE_USERNAME and KAGGLE_API_TOKEN are not set in .env")
    executable = Path(sys.executable).parent / "kaggle"
    return subprocess.run([str(executable), *args], capture_output=True, text=True, timeout=timeout)


def check_auth() -> str:
    """One cheap authenticated call. Returns a short description, or raises."""
    result = cli("kernels", "list", "--mine", "--page-size", "1", timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Kaggle auth check failed: {(result.stderr or result.stdout).strip()[-300:]}")
    return "authenticated"


def embed_file(path: Path) -> dict[str, str]:
    """A job input carried inside the script itself, base64 encoded."""
    return {"name": Path(path).name, "b64": base64.b64encode(Path(path).read_bytes()).decode("ascii")}


def url_input(name: str, url: str) -> dict[str, str]:
    """A job input the remote script downloads, for example a file at a pinned commit."""
    return {"name": name, "url": url}


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def build_job(slug: str, remote_script: str, job: dict[str, Any], *, gpu: bool = True) -> Path:
    """Write the folder Kaggle needs: run.py and kernel-metadata.json."""
    slug = slugify(slug)
    folder = config.JOBS / slug
    folder.mkdir(parents=True, exist_ok=True)

    source = (REMOTE / remote_script).read_text(encoding="utf-8")
    header = "JOB_JSON = r'''" + json.dumps(job, ensure_ascii=True) + "'''\n"
    (folder / "run.py").write_text(header + source, encoding="utf-8")

    metadata = {
        "id": f"{username()}/{slug}",
        "title": slug,
        "code_file": "run.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": gpu,
        "enable_internet": True,
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    if gpu:
        metadata["machine_shape"] = ACCELERATOR
    (folder / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return folder


def push(folder: Path, *, gpu: bool = True, timeout_s: int | None = None) -> str:
    """Start the job. Returns the kernel reference, owner/slug."""
    args = ["kernels", "push", "-p", str(folder)]
    if gpu:
        args += ["--accelerator", ACCELERATOR]
    if timeout_s:
        args += ["-t", str(int(timeout_s))]
    result = cli(*args)
    text = (result.stdout + result.stderr).strip()
    if result.returncode != 0 or "error" in text.lower():
        raise RuntimeError(f"Kaggle push failed: {text[-500:]}")
    return json.loads((folder / "kernel-metadata.json").read_text())["id"]


def status(ref: str) -> str:
    """One of: queued, running, complete, error, cancel, unknown."""
    result = cli("kernels", "status", ref, timeout=120)
    text = (result.stdout + result.stderr).lower()
    for word in ("complete", "error", "cancel", "running", "queued"):
        if word in text:
            return word
    return "unknown"


def wait(ref: str, *, poll_s: int = 45, timeout_s: int = 4 * 3600) -> str:
    """Poll until the job finishes. Returns its final status."""
    started = time.time()
    last = ""
    while time.time() - started < timeout_s:
        try:
            current = status(ref)
        except (subprocess.TimeoutExpired, OSError) as exc:
            current = f"unknown ({exc})"
        if current != last:
            minutes = (time.time() - started) / 60
            print(f"  [{ref}] {current} after {minutes:.1f} min")
            last = current
        if current in FINAL:
            return current
        time.sleep(poll_s)
    return "timeout"


def download(ref: str, dest: Path) -> list[Path]:
    """Download everything the job wrote to its working folder."""
    dest.mkdir(parents=True, exist_ok=True)
    result = cli("kernels", "output", ref, "-p", str(dest), "-o", timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(f"Kaggle output download failed: {(result.stderr or result.stdout).strip()[-400:]}")
    return sorted(p for p in dest.rglob("*") if p.is_file())


def run(slug: str, remote_script: str, job: dict[str, Any], dest: Path, *,
        gpu: bool = True, timeout_s: int = 4 * 3600) -> dict[str, Any]:
    """Build, push, wait and download. Returns the remote results.json plus job facts."""
    folder = build_job(slug, remote_script, job, gpu=gpu)
    started = time.time()
    ref = push(folder, gpu=gpu)
    print(f"  pushed {ref}; waiting (this can take a long time)")
    final = wait(ref, timeout_s=timeout_s)
    files = download(ref, dest) if final in ("complete", "error") else []
    results_path = dest / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    return {
        "ref": ref,
        "status": final,
        "wall_s": round(time.time() - started, 1),
        "files": [str(p) for p in files],
        "results": results,
    }
