"""Refuse to pass `make check` if a secret is about to be committed.

Three checks over every file git would track:

1. .env must be ignored by git.
2. No file may contain a value that is set in the local .env.
3. No file may contain text shaped like a known provider key.
"""
from __future__ import annotations

import re
import subprocess

from dotenv import dotenv_values

from .common import config

PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Kaggle API token": re.compile(r"KGAT_[0-9A-Za-z]{20,}"),
    "Hugging Face token": re.compile(r"hf_[0-9A-Za-z]{30,}"),
    "GitHub token": re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=config.ROOT, capture_output=True, text=True)


def candidate_files() -> list[str]:
    """Tracked files plus untracked files that are not ignored."""
    listed = _git("ls-files", "-co", "--exclude-standard")
    return [line for line in listed.stdout.splitlines() if line.strip()]


def scan() -> list[str]:
    problems: list[str] = []

    if (config.ROOT / ".env").exists() and _git("check-ignore", "-q", ".env").returncode != 0:
        problems.append(".env exists but is not ignored by git")

    local_values = {
        name: value.strip()
        for name, value in dotenv_values(config.ROOT / ".env").items()
        if value and len(value.strip()) >= 12
    }

    for name in candidate_files():
        path = config.ROOT / name
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary media
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{name}: contains something shaped like a {label}")
        for key_name, value in local_values.items():
            if value in text:
                problems.append(f"{name}: contains the value of {key_name} from .env")
    return problems


def main() -> int:
    problems = scan()
    if problems:
        print("Secret scan FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"Secret scan passed ({len(candidate_files())} files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
