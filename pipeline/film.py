"""The one command: run every stage from storyboard.json to the two finished films.

    validate -> narration -> keyframes -> shots -> music -> assemble -> qc

Each stage reads the storyboard and the files of the stages before it, and
skips any output whose inputs have not changed. Run it twice and the second
run calls no model. Change one keyframe prompt and one keyframe regenerates.

Options (also available through the Makefile as ONLY, SKIP and FORCE):
    --only keyframes,assemble      run only these stages
    --skip shots                   leave a stage out, for example the long GPU stage
    --force keyframes:s04          regenerate one named output even though it is cached
"""
from __future__ import annotations

import time
from typing import Any

from . import assemble, keyframes, music, narration, qc, shots, validate
from .common import cache

STAGES = ("narration", "keyframes", "shots", "music", "assemble", "qc")


def parse_force(text: str | None) -> dict[str, set[str]]:
    """'keyframes:s04,narration:s02' -> {'keyframes': {'s04'}, 'narration': {'s02'}}.

    A stage must always be named together with an output. There is deliberately
    no way to force a whole stage, because that would throw away hours of GPU work.
    """
    forced: dict[str, set[str]] = {}
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        stage, _, name = item.partition(":")
        if stage not in STAGES or not name:
            raise ValueError(f"--force needs stage:output, for example keyframes:s04 (got '{item}')")
        forced.setdefault(stage, set()).add(name)
    return forced


def select(only: str | None, skip: str | None) -> list[str]:
    chosen = [s.strip() for s in only.split(",")] if only else list(STAGES)
    skipped = {s.strip() for s in skip.split(",")} if skip else set()
    unknown = [s for s in [*chosen, *skipped] if s not in STAGES]
    if unknown:
        raise ValueError(f"unknown stage(s): {', '.join(unknown)}. Stages are: {', '.join(STAGES)}")
    return [s for s in STAGES if s in chosen and s not in skipped]


def main(only: str | None = None, force: str | None = None, skip: str | None = None) -> int:
    try:
        selected, forced = select(only, skip), parse_force(force)
        board = validate.load()
    except ValueError as exc:
        print(exc)
        return 2
    except validate.StoryboardError as exc:
        print("storyboard.json is not valid:")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1

    started = time.time()
    manifest = cache.Manifest()
    print(f"Running: {' -> '.join(selected)}\n")

    if "narration" in selected:
        timeline = narration.run(board, manifest, forced.get("narration"))
    else:
        timeline = narration.timeline_from_disk(board)
    problem = narration.timeline_problem(timeline)
    if problem:
        print(f"  WARNING {problem}")

    if "keyframes" in selected:
        keyframes.run(board, manifest, forced.get("keyframes"))
    if "shots" in selected:
        shots.run(board, manifest, forced.get("shots"))
    if "music" in selected:
        music.run(board, manifest, forced.get("music"))

    facts: dict[str, Any] | None = None
    if "assemble" in selected:
        facts = assemble.run(board, timeline)
        for fmt, path in facts["outputs"].items():
            print(f"  {fmt}: {path}")

    passed = True
    if "qc" in selected:
        if facts is None:
            facts = assemble.load_facts()
        passed = qc.run(board, timeline, facts)["passed"]

    print(f"\nDone in {time.time() - started:.0f}s. Film length {timeline['total_s']:.1f}s.")
    return 0 if passed else 1
