"""Validate storyboard.json before any stage runs.

Two layers:

1. The JSON Schema in schema/storyboard.schema.json (shape, types, ranges).
2. Checks a schema cannot express (unique ids, references that must resolve,
   total length inside the 60 to 90 second window).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .common import config

MIN_FILM_S = 60.0
MAX_FILM_S = 90.0


class StoryboardError(Exception):
    """The storyboard is missing or does not satisfy the contract."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def schema_problems(board: dict[str, Any], schema_path: Path | None = None) -> list[str]:
    schema = json.loads((schema_path or config.SCHEMA).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    problems = []
    for error in sorted(validator.iter_errors(board), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(part) for part in error.absolute_path) or "(top level)"
        problems.append(f"{where}: {error.message}")
    return problems


def semantic_problems(board: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    shots = board["shots"]

    ids = [shot["id"] for shot in shots]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"shots: id {duplicate} is used more than once")

    characters = {c["id"] for c in board["characters"]}
    if len(characters) != len(board["characters"]):
        problems.append("characters: ids must be unique")

    for shot in shots:
        sid = shot["id"]
        for ref in shot["keyframe"].get("characters", []):
            if ref not in characters:
                problems.append(f"{sid}: keyframe refers to unknown character '{ref}'")
        motion = shot["motion"]
        if motion["mode"] == "wan" and not motion.get("prompt", "").strip():
            problems.append(f"{sid}: motion.mode is 'wan' but motion.prompt is empty")
        if motion["mode"] == "wan" and "seed" not in motion:
            problems.append(f"{sid}: motion.mode is 'wan' but motion.seed is missing")
        narration = shot["narration"]
        if bool(narration["text"].strip()) != bool(narration["subtitle_en"].strip()):
            problems.append(f"{sid}: narration text and subtitle_en must both be set or both be empty")

    planned = sum(shot["duration_s"] for shot in shots) + board["end_card"]["duration_s"]
    if not MIN_FILM_S <= planned <= MAX_FILM_S:
        problems.append(
            f"planned length is {planned:.1f}s with the end card; it must be between "
            f"{MIN_FILM_S:.0f}s and {MAX_FILM_S:.0f}s"
        )

    music = board["music"]
    if music["chosen"] is not None and music["chosen"] >= len(music["seeds"]):
        problems.append("music: chosen must be an index into seeds")
    for cue in music.get("cues", []):
        if cue["shot"] not in ids:
            problems.append(f"music: cue refers to unknown shot '{cue['shot']}'")

    frames = board["video"]["num_frames"]
    if (frames - 1) % 4 != 0:
        problems.append(f"video: num_frames is {frames}; the model needs 4n+1 (for example 49, 81, 121)")

    card_text = " ".join(board["end_card"]["lines"]).lower()
    card_words = set(re.findall(r"[a-z]+", card_text))
    if "ai" not in card_words and "artificial intelligence" not in card_text:
        problems.append("end_card: the text must say the film was made with AI")

    return problems


def load(path: Path | None = None) -> dict[str, Any]:
    """Read and validate the storyboard. Raises StoryboardError with every problem found."""
    path = path or config.STORYBOARD
    if not path.exists():
        raise StoryboardError([
            f"{path.name} does not exist yet. Write story/brief.md, run `make draft`, "
            "then edit storyboard.draft.json and save it as storyboard.json."
        ])
    try:
        board = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoryboardError([f"{path.name} is not valid JSON: {exc}"]) from exc

    problems = schema_problems(board)
    if not problems:
        problems = semantic_problems(board)
    if problems:
        raise StoryboardError(problems)
    return board


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    path = Path(argv[0]) if argv else config.STORYBOARD
    try:
        board = load(path)
    except StoryboardError as exc:
        print(f"{path.name}: NOT valid")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1
    planned = sum(s["duration_s"] for s in board["shots"]) + board["end_card"]["duration_s"]
    print(f"{path.name}: valid ({len(board['shots'])} shots, planned {planned:.1f}s with the end card)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
