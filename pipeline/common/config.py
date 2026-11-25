"""Paths, environment and small helpers shared by every stage.

Every path is derived from the repository root, so the pipeline behaves the
same wherever the repository is cloned.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

STORYBOARD = ROOT / "storyboard.json"
SCHEMA = ROOT / "schema" / "storyboard.schema.json"
OUTPUTS = ROOT / "outputs"
MANIFEST = OUTPUTS / "manifest.json"
TIMELINE = OUTPUTS / "timeline.json"
RUNS = ROOT / "runs.jsonl"
STORE = ROOT / ".cache" / "store"
JOBS = ROOT / ".cache" / "jobs"
FONTS = ROOT / "assets" / "fonts"

FPS = 24
FORMATS = {
    "9x16": (1080, 1920),
    "16x9": (1920, 1080),
}


def env(name: str) -> str | None:
    """Return an environment value, or None when it is unset or blank."""
    value = os.environ.get(name, "").strip()
    return value or None


def rel(path: Path | str) -> str:
    """Path relative to the repository root, with forward slashes."""
    path = Path(path)
    if path.is_absolute():
        path = path.relative_to(ROOT)
    return path.as_posix()


def git_commit() -> str | None:
    """Short hash of the current commit, or None outside a repository."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None
