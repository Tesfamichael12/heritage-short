"""Content-addressed caching.

Each generated file has a key: a SHA-256 hash over everything that decides
what the file should be (stage version, model, parameters, prompts, seeds and
the content hashes of its input files). The key is recorded in
outputs/manifest.json next to the hash of the file itself.

A stage asks ``status(path, key)`` before doing any work:

- "fresh":   the manifest holds this key and the file on disk is unchanged
- "stale":   a file exists but was made from different inputs
- "missing": there is no file

Every generated file is also copied into .cache/store/ under its key, so
undoing an edit brings the earlier output back without a new model call.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


def _normalise(value: Any) -> Any:
    """Make text hash the same on every machine (Unicode NFC, no stray spaces)."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value).strip()
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def canonical(value: Any) -> bytes:
    """Canonical JSON: sorted keys, NFC text, no insignificant whitespace."""
    return json.dumps(
        _normalise(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_key(stage: str, version: int, spec: dict[str, Any],
             input_files: dict[str, Path] | None = None) -> str:
    """The cache key for one output.

    ``spec`` holds the model, parameters, prompts and seeds. ``input_files``
    are files this output is made from; their content is hashed, so a changed
    keyframe invalidates the clip made from it.
    """
    inputs = {name: file_sha256(path) for name, path in sorted((input_files or {}).items())}
    payload = {"stage": stage, "version": version, "spec": spec, "inputs": inputs}
    return hashlib.sha256(canonical(payload)).hexdigest()


class Manifest:
    """outputs/manifest.json: which key each output was made from."""

    def __init__(self, path: Path | None = None, store: Path | None = None):
        self.path = path or config.MANIFEST
        self.store = store or config.STORE
        self.root = self.path.parent.parent
        self.entries: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            self.entries = json.loads(self.path.read_text(encoding="utf-8"))

    def _rel(self, path: Path | str) -> str:
        path = Path(path)
        if path.is_absolute():
            path = path.relative_to(self.root)
        return path.as_posix()

    def _abs(self, path: Path | str) -> Path:
        path = Path(path)
        return path if path.is_absolute() else self.root / path

    def status(self, path: Path | str, key: str) -> str:
        file = self._abs(path)
        if not file.exists():
            return "missing"
        entry = self.entries.get(self._rel(path))
        if entry and entry.get("key") == key and entry.get("sha256") == file_sha256(file):
            return "fresh"
        return "stale"

    def commit(self, path: Path | str, key: str, *, stage: str, shot: str | None = None) -> None:
        """Record a freshly generated file and keep a copy in the store."""
        file = self._abs(path)
        self.entries[self._rel(path)] = {
            "key": key,
            "sha256": file_sha256(file),
            "stage": stage,
            "shot": shot,
            "bytes": file.stat().st_size,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.save()
        self.store.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, self.store / f"{key}{file.suffix}")

    def restore(self, path: Path | str, key: str, *, stage: str, shot: str | None = None) -> bool:
        """Bring an earlier output back from the store. True when it was there."""
        file = self._abs(path)
        stored = self.store / f"{key}{file.suffix}"
        if not stored.exists():
            return False
        file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stored, file)
        self.commit(file, key, stage=stage, shot=shot)
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(self.entries, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)
