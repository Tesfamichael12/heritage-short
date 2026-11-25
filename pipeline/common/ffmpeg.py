"""Thin wrappers around ffmpeg and ffprobe.

FFmpeg is always run from inside outputs/ with relative file names. Its
filter syntax treats ':' as a separator, so absolute paths are a trap.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import config


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], *, cwd: Path | None = None, quiet: bool = True) -> str:
    """Run ffmpeg with the given arguments and return its stderr text."""
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args]
    result = subprocess.run(command, cwd=cwd or config.OUTPUTS, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"ffmpeg failed ({result.returncode}):\n{tail}")
    if not quiet:
        print(result.stderr)
    return result.stderr


def probe(path: Path | str, *, cwd: Path | None = None) -> dict:
    """Stream and container facts for a media file, as ffprobe reports them."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        cwd=cwd or config.OUTPUTS, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path}: {result.stderr.strip()[-300:]}")
    return json.loads(result.stdout)


def duration(path: Path | str, *, cwd: Path | None = None) -> float:
    """Length of a media file in seconds."""
    return float(probe(path, cwd=cwd)["format"]["duration"])
