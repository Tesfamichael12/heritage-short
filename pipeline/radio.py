"""Radio cut: the whole narration over placeholder music on a black screen.

This is the cheapest prototype of the film. It exists to be played to the
audience before any picture is generated, so the story and its pacing can
change while changing them is still free.

The narration here is ONE speech call that reads every line in order. That
keeps the free speech quota for the final per-shot narration, and it is also
one side of experiment E1 (a single take against one call per line).

The music is a generated placeholder pad, not the film's score.
"""
from __future__ import annotations

from typing import Any

from . import validate
from .common import cache, config, ffmpeg, runlog
from .common.retry import MissingKey, QuotaExhausted
from .providers import gemini

STAGE = "radio"
VERSION = 1
RADIO = config.OUTPUTS / "radio"
TAKE = RADIO / "narration_take.wav"
PAD = RADIO / "placeholder_pad.wav"
CUT_MP4 = RADIO / "radio_cut.mp4"
CUT_MP3 = RADIO / "radio_cut.mp3"


def take_text(board: dict[str, Any]) -> str:
    """Every narration line in order, with a blank line between shots as a pause."""
    lines = [shot["narration"]["text"].strip() for shot in board["shots"]]
    return "\n\n".join(line for line in lines if line)


def take_key(board: dict[str, Any], model: str) -> str:
    narration = board["narration"]
    return cache.make_key(STAGE, VERSION, {
        "model": model,
        "voice": narration["voice"],
        "style_instruction": narration["style_instruction"],
        "text": take_text(board),
    })


def narration_take(board: dict[str, Any], manifest: cache.Manifest) -> tuple[str, str]:
    """Make the single take if the text changed. Returns ("reused"|"generated", model)."""
    narration = board["narration"]
    models = [narration["model"]]
    if narration.get("fallback_model"):
        models.append(narration["fallback_model"])

    for model in models:
        key = take_key(board, model)
        if manifest.status(TAKE, key) == "fresh" or manifest.restore(TAKE, key, stage=STAGE):
            return "reused", model

    last: Exception | None = None
    for model in models:
        key = take_key(board, model)
        try:
            wav = gemini.synthesize(
                model, take_text(board), voice=narration["voice"],
                style_instruction=narration["style_instruction"], stage=STAGE, cache_key=key,
            )
        except QuotaExhausted as exc:
            last = exc
            print(f"  {model} is out of quota for today")
            continue
        TAKE.parent.mkdir(parents=True, exist_ok=True)
        TAKE.write_bytes(wav)
        manifest.commit(TAKE, key, stage=STAGE)
        return "generated", model
    assert last is not None
    raise last


def placeholder_pad(seconds: float) -> None:
    """A soft D minor drone made by FFmpeg. Deterministic, and clearly not a score."""
    notes = [146.83, 174.61, 220.00, 293.66]  # D3 F3 A3 D4
    inputs: list[str] = []
    for frequency in notes:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={seconds:.2f}"]
    mix = "".join(f"[{i}:a]" for i in range(len(notes)))
    graph = (
        f"{mix}amix=inputs={len(notes)}:normalize=0,"
        "tremolo=f=0.15:d=0.5,lowpass=f=900,aecho=0.8:0.6:700:0.35,"
        f"volume=0.05,afade=t=in:d=2,afade=t=out:st={max(0.0, seconds - 3):.2f}:d=3[pad]"
    )
    ffmpeg.run([*inputs, "-filter_complex", graph, "-map", "[pad]", "-ar", "48000", "-ac", "2",
                config.rel(PAD).removeprefix("outputs/")])


def assemble(seconds: float) -> None:
    """Voice levelled to a speech loudness, pad underneath, black picture on top."""
    take, pad = "radio/narration_take.wav", "radio/placeholder_pad.wav"
    graph = (
        "[0:a]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11,aformat=channel_layouts=stereo,adelay=700|700[voice];"
        "[voice][1:a]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.89[mix]"
    )
    ffmpeg.run([
        "-i", take, "-i", pad,
        "-f", "lavfi", "-i", f"color=c=black:s=720x1280:r={config.FPS}:d={seconds:.2f}",
        "-filter_complex", graph, "-map", "2:v", "-map", "[mix]",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{seconds:.2f}",
        "-movflags", "+faststart", "radio/radio_cut.mp4",
    ])
    ffmpeg.run(["-i", "radio/radio_cut.mp4", "-vn", "-c:a", "libmp3lame", "-b:a", "128k", "radio/radio_cut.mp3"])


def main() -> int:
    try:
        board = validate.load()
    except validate.StoryboardError as exc:
        print("storyboard.json is not valid:")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1

    manifest = cache.Manifest()
    try:
        outcome, model = narration_take(board, manifest)
    except MissingKey as exc:
        print(f"Cannot make the narration: {exc}")
        return 1
    except QuotaExhausted:
        print("The speech quota is used up for today. It resets at 11:00 East Africa Time.")
        return 1

    spoken = ffmpeg.duration("radio/narration_take.wav")
    total = spoken + 3.0
    placeholder_pad(total)
    assemble(total)
    runlog.stage_summary(
        STAGE,
        reused=["narration_take"] if outcome == "reused" else [],
        generated=["narration_take"] if outcome == "generated" else [],
        note=f"single take with {model}; narration {spoken:.1f}s; radio cut {total:.1f}s",
    )

    planned = sum(s["duration_s"] for s in board["shots"])
    print(f"\nRadio cut ready ({total:.0f}s):")
    print(f"  {config.rel(CUT_MP4)}   black screen with sound")
    print(f"  {config.rel(CUT_MP3)}   audio only, easy to send")
    print(f"The narration alone runs {spoken:.1f}s. The storyboard plans {planned:.1f}s of shots.")
    if spoken > planned:
        print("  The narration is longer than the planned shots: trim lines or the film will stretch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
