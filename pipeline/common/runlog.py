"""runs.jsonl: one line for every model call attempt, including the failures.

Two kinds of line are written:

- "model_call": one attempt at one provider call, with model, parameters,
  seed, latency, cost and status.
- "stage_summary": one per stage run, with how many outputs were reused and
  how many were generated. This is the written proof that a re-run only
  regenerated what changed.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config

RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(2)
_COMMIT = config.git_commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def experiment_id() -> str | None:
    """The experiment this run belongs to, set with EXPERIMENT=E4."""
    return config.env("EXPERIMENT")


def write(record: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Append one record to runs.jsonl and return it."""
    record = {
        "ts": _now(),
        "run_id": RUN_ID,
        "git_commit": _COMMIT,
        "experiment_id": experiment_id(),
        **record,
    }
    target = path or config.RUNS
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


@contextmanager
def model_call(
    *,
    stage: str,
    provider: str,
    model: str,
    shot: str | None = None,
    params: dict[str, Any] | None = None,
    seed: int | None = None,
    prompt: str | None = None,
    inputs: dict[str, str] | None = None,
    cache_key: str | None = None,
    attempt: int = 1,
) -> Iterator[dict[str, Any]]:
    """Time one provider call and always log it, whether it works or fails.

    The caller fills in what only it knows, for example
    ``rec["output"] = "outputs/keyframes/s01.png"`` and ``rec["cost"] = {...}``.
    """
    rec: dict[str, Any] = {
        "event": "model_call",
        "stage": stage,
        "shot": shot,
        "provider": provider,
        "model": model,
        "params": params or {},
        "seed": seed,
        "prompt": prompt,
        "inputs": inputs or {},
        "cache_key": cache_key,
        "attempt": attempt,
        "output": None,
        "cost": None,
    }
    started = time.perf_counter()
    try:
        yield rec
        rec.setdefault("status", "ok")
    except BaseException as exc:  # logged, then re-raised
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {exc}"[:600]
        raise
    finally:
        rec["latency_s"] = round(time.perf_counter() - started, 3)
        write(rec)


def stage_summary(stage: str, *, reused: list[str], generated: list[str],
                  failed: list[str] | None = None, note: str | None = None) -> None:
    """Record what one stage run reused and what it regenerated."""
    write({
        "event": "stage_summary",
        "stage": stage,
        "reused": len(reused),
        "generated": len(generated),
        "failed": len(failed or []),
        "generated_items": generated,
        "failed_items": failed or [],
        "note": note,
    })
    line = f"[{stage}] reused {len(reused)}, generated {len(generated)}"
    if failed:
        line += f", failed {len(failed)}: {', '.join(failed)}"
    if generated:
        line += f"  ({', '.join(generated)})"
    print(line)


def read(path: Path | None = None) -> list[dict[str, Any]]:
    """All records in runs.jsonl, skipping any line that is not valid JSON."""
    target = path or config.RUNS
    if not target.exists():
        return []
    records = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
