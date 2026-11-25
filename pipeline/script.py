"""Script stage: draft a storyboard from the story, for a person to edit.

Reads story/brief.md (the story in the author's own words) and asks Gemini for
a storyboard that satisfies the schema. The result is written to
storyboard.draft.json. It never touches storyboard.json: a person reads the
draft, corrects the narration, and saves it as the real storyboard.

This stage is not part of `make film`. The storyboard is the source of truth;
this only helps to write its first version.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import validate
from .common import config
from .providers import gemini

MODEL = config.env("DRAFT_MODEL") or "gemini-3.8-flash"
BRIEF = config.ROOT / "story" / "brief.md"
EXAMPLE = config.ROOT / "examples" / "storyboard.example.json"
DRAFT = config.ROOT / "storyboard.draft.json"

INSTRUCTIONS = """You are helping a first-time filmmaker plan a 60 to 90 second short film about their family.
Write a storyboard as one JSON object that satisfies the JSON Schema below. Return JSON only.

How to plan it:
- 8 to 12 shots. Planned shot lengths plus the end card must total about 72 seconds.
- Stay faithful to the story as told. Do not invent facts about real people.
- One idea and one movement per shot. Every shot needs a `reason` that says why the film needs it.
- Vary shot sizes: a wide shot to show where we are, medium shots for what happens, close-ups for feeling.
- Prefer one person and one place. Show hands, objects and places more often than faces.

Narration (`narration.text`), in the language with code "{language}":
- Written for the ear: short sentences, concrete images, natural spoken words a grandparent would use.
- One or two sentences per shot, short enough to say comfortably within that shot's length.
- `subtitle_en` is a faithful, plain English translation of that line.

Pictures:
- `style.style_block` describes qualities (medium, palette, light, texture). Never name an artist.
- `characters[].description` is fixed wording reused in every prompt, so make it specific:
  age, face, hair, clothes with colours. Use an illustrated look, not a photograph of a real person.
- `keyframe.prompt` describes what the shot shows, with the subject in the centre of a square frame.
  No words, letters or signs inside the picture.
- `motion.prompt` describes only movement and camera, because the image already holds the subject.
  Keep motion slow and gentle. Give the three most important shots mode "wan" and the rest "kenburns".
  `priority` 1 is the most important shot.

Music: an instrumental underscore that leaves room for the voice, with no strong lead melody.
Tempo and key go in `bpm` and `keyscale`, not in the caption. Set `chosen` to null.

Copy these blocks from the example unchanged: narration.model, narration.fallback_model, keyframes,
video, mix, music.model, music.seeds, music.duration_s. The end card must say the film was made with AI.
Leave private details (full names, addresses) out of every prompt.
"""


def build_prompt(brief: str, language: str = "am") -> str:
    schema = config.SCHEMA.read_text(encoding="utf-8")
    example = EXAMPLE.read_text(encoding="utf-8")
    return (
        INSTRUCTIONS.format(language=language)
        + "\n\n## The story, in the author's words\n\n" + brief.strip()
        + "\n\n## JSON Schema\n\n" + schema
        + "\n\n## An example of the format (a different story)\n\n" + example
    )


def parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def problems_of(board: dict) -> list[str]:
    found = validate.schema_problems(board)
    return found or validate.semantic_problems(board)


def draft(brief: str, language: str = "am") -> tuple[dict, list[str]]:
    """Ask for a storyboard; if it breaks the contract, ask once more with the problems."""
    prompt = build_prompt(brief, language)
    board = parse(gemini.generate_text(MODEL, prompt, stage="script", json_mode=True))
    problems = problems_of(board)
    if problems:
        print(f"  first draft has {len(problems)} problem(s); asking for a corrected version")
        repair = (
            prompt
            + "\n\n## Your previous answer\n\n" + json.dumps(board, ensure_ascii=False)
            + "\n\n## It breaks the contract in these ways. Return the corrected JSON only.\n\n"
            + "\n".join(f"- {p}" for p in problems[:40])
        )
        board = parse(gemini.generate_text(MODEL, repair, stage="script", json_mode=True))
        problems = problems_of(board)
    return board, problems


def main(brief_path: Path | None = None) -> int:
    brief_path = brief_path or BRIEF
    if not brief_path.exists() or len(brief_path.read_text(encoding="utf-8").strip()) < 80:
        print(f"Write the story in {config.rel(brief_path)} first (a few paragraphs in your own words).")
        return 1

    board, problems = draft(brief_path.read_text(encoding="utf-8"))
    DRAFT.write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {config.rel(DRAFT)} ({len(board.get('shots', []))} shots).")
    if problems:
        print("It still has problems to fix by hand:")
        for problem in problems:
            print(f"  - {problem}")
    print("Read every narration line aloud, correct it, then save the file as storyboard.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
