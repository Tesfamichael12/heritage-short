"""English subtitles from the storyboard and the timeline.

The speech model returns no word timings, so each line's subtitle is timed
from that line's measured audio: the text is split into cues of at most two
short lines, and the cues share the line's duration in proportion to their
length.

Two outputs: an SRT file (a separate deliverable that players can switch on
or off) and one ASS file per aspect ratio, which FFmpeg burns into the
picture. Line breaks are decided here, never by the renderer, so a cue is
guaranteed to be at most two lines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LINGER_S = 0.25      # a cue stays briefly after the voice stops
MIN_CUE_S = 0.9

# Vertical video is narrow, so its lines are shorter and its text sits higher,
# clear of the caption and button area that phone apps draw at the bottom.
LAYOUT = {
    "9x16": {"max_chars": 30, "font_size": 56, "margin_v": 400, "margin_h": 90},
    "16x9": {"max_chars": 40, "font_size": 54, "margin_v": 80, "margin_h": 160},
}
SRT_MAX_CHARS = 40
FONT_NAME = "Noto Sans"


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    lines: tuple[str, ...]


def wrap(text: str, max_chars: int) -> list[str]:
    """Greedy word wrap. A single word longer than the limit gets its own line."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def balance(first: str, second: str, max_chars: int) -> tuple[str, str]:
    """Even out a two-line cue so the second line is not a lonely word."""
    words = f"{first} {second}".split()
    best = (first, second)
    best_gap = abs(len(first) - len(second))
    for cut in range(1, len(words)):
        a, b = " ".join(words[:cut]), " ".join(words[cut:])
        if len(a) <= max_chars and len(b) <= max_chars and abs(len(a) - len(b)) < best_gap:
            best, best_gap = (a, b), abs(len(a) - len(b))
    return best


def split_text(text: str, max_chars: int, max_lines: int = 2) -> list[tuple[str, ...]]:
    """Split one subtitle into cues of at most `max_lines` lines."""
    lines = wrap(text, max_chars)
    groups = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]
    cues = []
    for group in groups:
        if len(group) == 2:
            group = list(balance(group[0], group[1], max_chars))
        cues.append(tuple(group))
    return cues


def cues_for_line(start: float, spoken: float, limit: float, text: str, max_chars: int) -> list[Cue]:
    """Cues for one narration line, sharing its duration by length. `limit` is the shot's end."""
    groups = split_text(text, max_chars)
    if not groups:
        return []
    span = min(start + spoken + LINGER_S, limit) - start
    wanted = MIN_CUE_S * len(groups)
    if span < wanted:  # give short lines a readable minimum, without leaving the shot
        span = max(span, min(wanted, limit - start))
    weights = [max(1, sum(len(line) for line in group)) for group in groups]
    total = float(sum(weights))
    cues, cursor = [], start
    for group, weight in zip(groups, weights):
        length = span * weight / total
        cues.append(Cue(round(cursor, 3), round(min(cursor + length, limit), 3), group))
        cursor += length
    return cues


def build(board: dict[str, Any], timeline: dict[str, Any], max_chars: int) -> list[Cue]:
    """Every cue of the film, in order."""
    times = {shot["id"]: shot for shot in timeline["shots"]}
    cues: list[Cue] = []
    for shot in board["shots"]:
        text = shot["narration"]["subtitle_en"].strip()
        timing = times.get(shot["id"])
        if not text or not timing or timing.get("narration_start_s") is None:
            continue
        shot_end = timing["start_s"] + timing["duration_s"]
        cues += cues_for_line(timing["narration_start_s"], timing["narration_s"], shot_end, text, max_chars)
    return cues


def _srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _ass_time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, rest = divmod(centis, 360_000)
    minutes, rest = divmod(rest, 6000)
    secs, centis = divmod(rest, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n" + "\n".join(cue.lines)
        for index, cue in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_ass(cues: list[Cue], width: int, height: int, fmt: str) -> str:
    layout = LAYOUT[fmt]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{layout['font_size']},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{layout['margin_h']},{layout['margin_h']},{layout['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        text = "\\N".join(line.replace("{", "(").replace("}", ")") for line in cue.lines)
        events.append(f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},Default,,0,0,0,,{text}")
    return header + "\n".join(events) + "\n"
