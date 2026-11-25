from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.common import config  # noqa: E402


@pytest.fixture
def board() -> dict:
    """A valid storyboard that each test can change freely."""
    text = (ROOT / "examples" / "storyboard.example.json").read_text(encoding="utf-8")
    return copy.deepcopy(json.loads(text))


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    """Tests never write to the real runs.jsonl."""
    monkeypatch.setattr(config, "RUNS", tmp_path / "runs.jsonl")
    monkeypatch.delenv("EXPERIMENT", raising=False)
    return tmp_path / "runs.jsonl"
