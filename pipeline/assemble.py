"""Assembly stage: the edit, in code, from the storyboard.

Nothing here calls a model. FFmpeg is deterministic, so the same inputs give
the same film.

The film is always renderable:
- a shot with a clip plays the clip, then holds on its last frame with a slow push
- a shot without a clip gets a slow pan and zoom over its keyframe
- a shot without even a keyframe gets a plain placeholder card (and QC fails)

Steps:
1. One video-only segment per shot and per aspect ratio, an exact number of frames.
   Segments are stored by a hash of their inputs, so only changed shots re-render.
2. One soundtrack: narration placed on the timeline, the score ducked under it,
   then loudness set in two passes.
3. Subtitles and fades burned in on the final pass, once per aspect ratio.

FFmpeg 4.4 traps this code avoids (each was reproduced on the build machine):
- sidechaincompress stops when the sidechain ends   -> the voice is padded to full length
- amix divides every input by the input count       -> normalize=0
- loudnorm outputs 192 kHz and returns "-inf"        -> -ar 48000, and "-inf" is parsed
- zoompan wobbles and defaults to 25 fps, 1280x720  -> the still is enlarged first; fps and size are set
- filters split file paths on ':'                    -> FFmpeg runs inside outputs/ with relative names
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import subtitles
from .common import cache, config, ffmpeg, runlog

STAGE = "assemble"
VERSION = 1
# AAC encoding overshoots the true peak a little (measured -0.8 dBTP on a -1.0 target,
# FAILURES.md F8), so the loudness pass aims this far below the limit.
AAC_HEADROOM_DB = 1.0
SEGMENTS = config.ROOT / ".cache" / "segments"
AUDIO = config.ROOT / ".cache" / "audio"
FINAL = config.OUTPUTS / "final"
PRESCALE = 3          # stills are enlarged this much before zoompan, which removes its wobble
CLIP_TAIL_TRIM = 4    # frames dropped from the end of a generated clip (often its weakest)
HOLD_ZOOM_PER_FRAME = 0.0006
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(config.FPS), "-an"]
CARD_BACKGROUND = (16, 14, 12)
CARD_TEXT = (240, 232, 220)


# --- paths -------------------------------------------------------------------

def out_rel(path: Path) -> str:
    """A path as FFmpeg sees it from inside outputs/. Never contains a colon."""
    path = Path(path).resolve()
    try:
        return path.relative_to(config.OUTPUTS).as_posix()
    except ValueError:
        return "../" + path.relative_to(config.ROOT).as_posix()


def keyframe_path(shot_id: str) -> Path:
    return config.OUTPUTS / "keyframes" / f"{shot_id}.png"


def clip_path(shot_id: str) -> Path:
    return config.OUTPUTS / "shots" / f"{shot_id}.mp4"


def narration_path(shot_id: str) -> Path:
    return config.OUTPUTS / "narration" / f"{shot_id}.wav"


def music_path(board: dict[str, Any]) -> tuple[Path | None, str]:
    """The chosen score, or the first candidate that exists, or nothing."""
    music = board["music"]
    folder = config.OUTPUTS / "music"
    if music["chosen"] is not None:
        chosen = folder / f"cand_{music['seeds'][music['chosen']]}.wav"
        if chosen.exists():
            return chosen, "chosen"
    for seed in music["seeds"]:
        candidate = folder / f"cand_{seed}.wav"
        if candidate.exists():
            return candidate, "first_candidate_not_yet_chosen"
    return None, "placeholder"


# --- geometry ----------------------------------------------------------------

def crop_box(src_w: int, src_h: int, out_w: int, out_h: int, focus_x: float = 0.5, focus_y: float = 0.5) -> tuple[int, int, int, int]:
    """The largest box with the output's shape that fits the source, centred on the focus point."""
    target = out_w / out_h
    if src_w / src_h > target:
        height, width = src_h, int(round(src_h * target))
    else:
        width, height = src_w, int(round(src_w / target))
    width -= width % 2
    height -= height % 2
    x = int(round(focus_x * src_w - width / 2))
    y = int(round(focus_y * src_h - height / 2))
    x = max(0, min(x, src_w - width))
    y = max(0, min(y, src_h - height))
    return width, height, x, y


def zoompan(frames: int, out_w: int, out_h: int, zoom_from: float, zoom_to: float, pan: str = "none") -> str:
    """The zoompan filter for a slow, even move across a still."""
    steps = max(1, frames - 1)
    progress = f"(on/{steps})"
    if pan != "none":  # a pan needs room to travel
        zoom_from, zoom_to = max(zoom_from, 1.10), max(zoom_to, 1.10)
    zoom = f"{zoom_from}+({zoom_to}-{zoom_from})*{progress}"
    low, high = 0.15, 0.85
    fx = {"right": f"({low}+({high}-{low})*{progress})", "left": f"({high}-({high}-{low})*{progress})"}.get(pan, "0.5")
    fy = {"down": f"({low}+({high}-{low})*{progress})", "up": f"({high}-({high}-{low})*{progress})"}.get(pan, "0.5")
    return (
        f"zoompan=z='{zoom}':x='(iw-iw/zoom)*{fx}':y='(ih-ih/zoom)*{fy}'"
        f":d={frames}:s={out_w}x{out_h}:fps={config.FPS}"
    )


# --- segments ----------------------------------------------------------------

def segment_key(kind: str, fmt: str, frames: int, source: Path | None, spec: dict[str, Any]) -> str:
    inputs = {"source": source} if source else None
    return cache.make_key(STAGE, VERSION, {"kind": kind, "format": fmt, "frames": frames, **spec}, inputs)


def render_kenburns(still: Path, target: Path, fmt: str, frames: int, shot: dict[str, Any]) -> None:
    out_w, out_h = config.FORMATS[fmt]
    with Image.open(still) as image:
        src_w, src_h = image.size
    framing, motion = shot.get("framing", {}), shot["motion"]
    w, h, x, y = crop_box(src_w, src_h, out_w, out_h, framing.get("focus_x", 0.5), framing.get("focus_y", 0.5))
    chain = (
        f"crop={w}:{h}:{x}:{y},scale={out_w * PRESCALE}:{out_h * PRESCALE}:flags=lanczos,"
        + zoompan(frames, out_w, out_h, motion.get("zoom_from", 1.0), motion.get("zoom_to", 1.1), motion.get("pan", "none"))
        + ",format=yuv420p"
    )
    ffmpeg.run(["-i", out_rel(still), "-vf", chain, "-frames:v", str(frames), *X264, out_rel(target)])


def clip_frames(clip: Path) -> tuple[int, int, int]:
    """Frame count, width and height of a generated clip."""
    info = ffmpeg.probe(out_rel(clip))
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    count = int(video.get("nb_frames") or round(float(info["format"]["duration"]) * config.FPS))
    return count, int(video["width"]), int(video["height"])


def render_clip(clip: Path, target: Path, fmt: str, frames: int, shot: dict[str, Any]) -> None:
    """Play the clip, then hold on its last frame with a slow push if the shot is longer."""
    out_w, out_h = config.FORMATS[fmt]
    count, src_w, src_h = clip_frames(clip)
    framing = shot.get("framing", {})
    w, h, x, y = crop_box(src_w, src_h, out_w, out_h, framing.get("focus_x", 0.5), framing.get("focus_y", 0.5))
    play = max(1, min(count - CLIP_TAIL_TRIM, frames))
    shape = f"crop={w}:{h}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos"
    moving = f"[0:v]fps={config.FPS},trim=end_frame={play},setpts=PTS-STARTPTS,{shape},format=yuv420p[a]"
    hold = frames - play

    if hold <= 0:
        ffmpeg.run(["-i", out_rel(clip), "-filter_complex", moving, "-map", "[a]",
                    "-frames:v", str(frames), *X264, out_rel(target)])
        return

    last = target.with_suffix(".last.png")
    ffmpeg.run(["-i", out_rel(clip), "-vf", f"fps={config.FPS},select='eq(n\\,{play - 1})',{shape}",
                "-frames:v", "1", out_rel(last)])
    still = (
        f"[1:v]scale={out_w * PRESCALE}:{out_h * PRESCALE}:flags=lanczos,"
        + zoompan(hold, out_w, out_h, 1.0, 1.0 + HOLD_ZOOM_PER_FRAME * hold)
        + ",format=yuv420p[b]"
    )
    ffmpeg.run(["-i", out_rel(clip), "-i", out_rel(last),
                "-filter_complex", f"{moving};{still};[a][b]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                "-frames:v", str(frames), *X264, out_rel(target)])
    last.unlink(missing_ok=True)


def _font(bold: bool, size: int, ethiopic: bool) -> ImageFont.FreeTypeFont:
    family = "NotoSansEthiopic" if ethiopic else "NotoSans"
    return ImageFont.truetype(str(config.FONTS / f"{family}-{'Bold' if bold else 'Regular'}.ttf"), size)


def _runs(text: str) -> list[tuple[str, bool]]:
    """Split text into runs of Ethiopic and non-Ethiopic characters, so each gets a font that has it."""
    runs: list[tuple[str, bool]] = []
    for char in text:
        ethiopic = "ሀ" <= char <= "᎟" or "ⶀ" <= char <= "⷟"
        if runs and (runs[-1][1] == ethiopic or char.isspace()):
            runs[-1] = (runs[-1][0] + char, runs[-1][1])
        else:
            runs.append((char, ethiopic))
    return runs


def draw_card(lines: list[str], fmt: str, target: Path, background=CARD_BACKGROUND) -> None:
    """A text card: the first line large, the rest smaller, all centred."""
    out_w, out_h = config.FORMATS[fmt]
    image = Image.new("RGB", (out_w, out_h), background)
    draw = ImageDraw.Draw(image)
    base = out_w // 18 if fmt == "9x16" else out_h // 16
    max_width = int(out_w * 0.84)

    laid_out = []
    for index, line in enumerate(lines):
        size = int(base * (1.25 if index == 0 else 0.62))
        while True:  # shrink a line until it fits the width
            pieces = [(text, _font(index == 0, size, ethiopic)) for text, ethiopic in _runs(line)]
            width = sum(draw.textlength(text, font=font) for text, font in pieces)
            if width <= max_width or size <= 18:
                break
            size -= 2
        laid_out.append((pieces, width, size))

    gap = int(base * 0.55)
    total = sum(size for _, _, size in laid_out) + gap * (len(laid_out) - 1) + (int(base * 0.5) if len(laid_out) > 1 else 0)
    y = (out_h - total) // 2
    for index, (pieces, width, size) in enumerate(laid_out):
        x = (out_w - width) / 2
        for text, font in pieces:
            draw.text((x, y), text, font=font, fill=CARD_TEXT)
            x += draw.textlength(text, font=font)
        y += size + gap + (int(base * 0.5) if index == 0 else 0)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG")


def render_card(card: Path, target: Path, frames: int, fade_in: bool = True) -> None:
    chain = "format=yuv420p" + (",fade=t=in:st=0:d=0.4" if fade_in else "")
    ffmpeg.run(["-loop", "1", "-framerate", str(config.FPS), "-i", out_rel(card), "-vf", chain,
                "-frames:v", str(frames), *X264, out_rel(target)])


def build_segments(board: dict[str, Any], timeline: dict[str, Any], fmt: str) -> tuple[list[Path], list[str], list[str], dict[str, str]]:
    """Render what changed. Returns (segment files in order, reused, rendered, source per shot)."""
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    times = {shot["id"]: shot for shot in timeline["shots"]}
    files, reused, rendered, sources = [], [], [], {}

    for shot in board["shots"]:
        sid, frames = shot["id"], times[shot["id"]]["frames"]
        clip, still = clip_path(sid), keyframe_path(sid)
        framing = shot.get("framing", {})
        if shot["motion"]["mode"] == "wan" and clip.exists():
            kind, source, spec = "clip", clip, {"framing": framing, "tail_trim": CLIP_TAIL_TRIM}
        elif still.exists():
            kind, source = "kenburns", still
            spec = {"framing": framing, "prescale": PRESCALE,
                    "motion": {k: shot["motion"].get(k) for k in ("zoom_from", "zoom_to", "pan")}}
        else:
            kind, source, spec = "missing", None, {"label": sid}
        sources[sid] = kind

        target = SEGMENTS / f"{segment_key(kind, fmt, frames, source, spec)}.mp4"
        files.append(target)
        if target.exists():
            reused.append(f"{sid}/{fmt}")
            continue
        if kind == "clip":
            render_clip(clip, target, fmt, frames, shot)
        elif kind == "kenburns":
            render_kenburns(still, target, fmt, frames, shot)
        else:
            card = SEGMENTS / f"missing_{sid}_{fmt}.png"
            draw_card([sid, "keyframe not generated yet"], fmt, card, background=(40, 40, 44))
            render_card(card, target, frames, fade_in=False)
        rendered.append(f"{sid}/{fmt}")

    lines = board["end_card"]["lines"]
    card_frames = timeline["end_card"]["frames"]
    target = SEGMENTS / f"{segment_key('end_card', fmt, card_frames, None, {'lines': lines})}.mp4"
    files.append(target)
    if target.exists():
        reused.append(f"end_card/{fmt}")
    else:
        card = FINAL / f"end_card_{fmt}.png"
        draw_card(lines, fmt, card)
        render_card(card, target, card_frames)
        rendered.append(f"end_card/{fmt}")
    return files, reused, rendered, sources


def concat(files: list[Path], fmt: str) -> Path:
    listing = SEGMENTS / f"concat_{fmt}.txt"
    listing.write_text("".join(f"file '{file.name}'\n" for file in files), encoding="utf-8")
    target = SEGMENTS / f"video_{fmt}.mp4"
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", out_rel(listing), "-c", "copy", out_rel(target)])
    return target


# --- sound -------------------------------------------------------------------

def measure_loudness(path: Path) -> dict[str, float]:
    """Integrated loudness and true peak of a file, as loudnorm's first pass reports them."""
    stderr = ffmpeg.run(["-i", out_rel(path), "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
                         "-f", "null", "-"])
    block = json.loads(re.findall(r"\{[^{}]*\}", stderr, flags=re.S)[-1])

    def number(name: str) -> float:
        value = str(block.get(name, "-inf"))
        return float("-inf") if "inf" in value else float(value)

    return {name: number(name) for name in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


def placeholder_music(seconds: float, target: Path) -> None:
    """A soft drone, used only until a real score candidate exists. QC reports it."""
    notes = [146.83, 174.61, 220.00, 293.66]
    inputs: list[str] = []
    for frequency in notes:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration={seconds:.2f}"]
    mix = "".join(f"[{i}:a]" for i in range(len(notes)))
    graph = f"{mix}amix=inputs={len(notes)}:normalize=0,tremolo=f=0.15:d=0.5,lowpass=f=900,aecho=0.8:0.6:700:0.35[pad]"
    ffmpeg.run([*inputs, "-filter_complex", graph, "-map", "[pad]", "-ar", "48000", "-ac", "2", out_rel(target)])


def _gain(target_lufs: float, measured: float, limit: float = 14.0) -> float:
    if measured == float("-inf"):
        return 0.0
    return max(-limit, min(limit, target_lufs - measured))


def build_audio(board: dict[str, Any], timeline: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """The finished soundtrack as a WAV, plus the numbers that describe it."""
    AUDIO.mkdir(parents=True, exist_ok=True)
    mix_spec, total = board["mix"], timeline["total_s"]
    lines = [(shot["id"], narration_path(shot["id"]), shot["narration_start_s"])
             for shot in timeline["shots"]
             if shot["narration_start_s"] is not None and narration_path(shot["id"]).exists()]
    music, music_source = music_path(board)

    key_inputs: dict[str, Path] = {f"voice_{sid}": path for sid, path, _ in lines}
    if music:
        key_inputs["music"] = music
    key = cache.make_key(STAGE, VERSION, {
        "kind": "audio", "mix": mix_spec, "total": total, "aac_headroom_db": AAC_HEADROOM_DB,
        "starts": {sid: start for sid, _, start in lines}, "music_source": music_source,
    }, key_inputs)
    target, facts_path = AUDIO / f"{key}.wav", AUDIO / f"{key}.json"
    if target.exists() and facts_path.exists():
        return target, {**json.loads(facts_path.read_text()), "reused": True}

    if music is None:
        music = AUDIO / "placeholder_music.wav"
        placeholder_music(total + 2, music)

    voice_gains = {sid: _gain(mix_spec.get("voice_lufs", -16), measure_loudness(path)["input_i"])
                   for sid, path, _ in lines}
    music_gain = _gain(mix_spec.get("music_lufs", -20), measure_loudness(music)["input_i"], limit=30.0)

    inputs: list[str] = []
    graph: list[str] = []
    for index, (sid, path, start) in enumerate(lines):
        inputs += ["-i", out_rel(path)]
        delay = int(round(start * 1000))
        graph.append(f"[{index}:a]aresample=48000,volume={voice_gains[sid]:.2f}dB,"
                     f"aformat=channel_layouts=stereo,adelay={delay}|{delay}[v{index}]")
    if lines:
        joined = "".join(f"[v{i}]" for i in range(len(lines)))
        graph.append(f"{joined}amix=inputs={len(lines)}:normalize=0:duration=longest,apad=whole_dur={total:.3f}[voice]")
    else:
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[voice]")
    graph.append("[voice]asplit=2[voice_mix][voice_key]")

    music_index = len(lines)
    inputs += ["-stream_loop", "-1", "-i", out_rel(music)]
    fade_out = max(0.0, total - 3.0)
    graph.append(
        f"[{music_index}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
        f"volume={music_gain:.2f}dB,afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out:.3f}:d=3[music]"
    )
    duck = mix_spec["duck"]
    graph.append(
        f"[music][voice_key]sidechaincompress=threshold={duck['threshold']}:ratio={duck['ratio']}"
        f":attack={duck['attack_ms']}:release={duck['release_ms']}[ducked]"
    )
    graph.append("[ducked][voice_mix]amix=inputs=2:normalize=0:duration=first[mix]")

    premix = AUDIO / f"{key}.premix.wav"
    ffmpeg.run([*inputs, "-filter_complex", ";".join(graph), "-map", "[mix]", "-t", f"{total:.3f}",
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", out_rel(premix)])

    # Two-pass loudness: measure the mix, then apply one fixed correction.
    first = measure_loudness(premix)
    target_i, target_tp = mix_spec["target_lufs"], mix_spec["true_peak_db"] - AAC_HEADROOM_DB
    correction = (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:measured_I={first['input_i']}:measured_TP={first['input_tp']}"
        f":measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}:offset={first['target_offset']}"
        ":linear=true:print_format=json"
    )
    stderr = ffmpeg.run(["-i", out_rel(premix), "-af", correction, "-ar", "48000", "-ac", "2",
                         "-c:a", "pcm_s24le", out_rel(target)])
    second = json.loads(re.findall(r"\{[^{}]*\}", stderr, flags=re.S)[-1])
    premix.unlink(missing_ok=True)

    facts = {
        "music_source": music_source,
        "voice_lines": len(lines),
        "voice_gain_db": {sid: round(gain, 2) for sid, gain in voice_gains.items()},
        "music_gain_db": round(music_gain, 2),
        "premix_lufs": first["input_i"],
        "premix_true_peak_db": first["input_tp"],
        "loudnorm_mode": second.get("normalization_type"),
        "loudnorm_output_lufs": float(second.get("output_i", "nan")),
        "loudnorm_output_true_peak_db": float(second.get("output_tp", "nan")),
        "duck": duck,
    }
    facts_path.write_text(json.dumps(facts, indent=2), encoding="utf-8")
    return target, {**facts, "reused": False}


# --- the final pass ----------------------------------------------------------

def write_subtitles(board: dict[str, Any], timeline: dict[str, Any]) -> int:
    FINAL.mkdir(parents=True, exist_ok=True)
    srt = subtitles.build(board, timeline, subtitles.SRT_MAX_CHARS)
    (FINAL / "heritage.srt").write_text(subtitles.to_srt(srt), encoding="utf-8")
    for fmt, (width, height) in config.FORMATS.items():
        cues = subtitles.build(board, timeline, subtitles.LAYOUT[fmt]["max_chars"])
        (FINAL / f"subtitles_{fmt}.ass").write_text(subtitles.to_ass(cues, width, height, fmt), encoding="utf-8")
    return len(srt)


def export(segments: list[Path], audio: Path, fmt: str, board: dict[str, Any], total: float) -> tuple[Path, bool]:
    """Join the segments and burn in subtitles and fades. Skipped when nothing changed.

    Returns the film's path and whether it was re-encoded.
    """
    target = FINAL / f"heritage_{fmt}.mp4"
    ass = (FINAL / f"subtitles_{fmt}.ass").read_text(encoding="utf-8")
    key = cache.make_key(STAGE, VERSION, {
        "kind": "export", "format": fmt, "segments": [file.name for file in segments],
        "audio": audio.name, "subtitles": ass, "total": total,
        "title": board["film"]["title"], "end_card": board["end_card"]["lines"],
    })
    marker = SEGMENTS / f"export_{fmt}.key"
    if target.exists() and marker.exists() and marker.read_text() == key:
        return target, False

    video = concat(segments, fmt)
    fade_out = max(0.0, total - 0.6)
    chain = (
        f"fade=t=in:st=0:d=0.5,fade=t=out:st={fade_out:.3f}:d=0.6,"
        f"ass=final/subtitles_{fmt}.ass:fontsdir=../assets/fonts"
    )
    ffmpeg.run([
        "-i", out_rel(video), "-i", out_rel(audio), "-vf", chain,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(config.FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-metadata", f"title={board['film']['title']}",
        "-metadata", "comment=Made with AI. " + " | ".join(board["end_card"]["lines"]),
        "-movflags", "+faststart", "-t", f"{total:.3f}", out_rel(target),
    ])
    marker.write_text(key)
    return target, True


def load_facts() -> dict[str, Any]:
    """The facts of the last assembly, for running the quality check on its own."""
    path = FINAL / "assembly.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def run(board: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
    """Build both films. Returns facts that QC writes into its report."""
    FINAL.mkdir(parents=True, exist_ok=True)
    cue_count = write_subtitles(board, timeline)
    audio, audio_facts = build_audio(board, timeline)

    reused_all, rendered_all, sources, outputs, encoded = [], [], {}, {}, []
    for fmt in config.FORMATS:
        files, reused, rendered, sources = build_segments(board, timeline, fmt)
        reused_all += reused
        rendered_all += rendered
        film, was_encoded = export(files, audio, fmt, board, timeline["total_s"])
        outputs[fmt] = config.rel(film)
        if was_encoded:
            encoded.append(fmt)

    note = "FFmpeg only; no model was called. Final encode: " + (", ".join(encoded) if encoded else "unchanged, skipped")
    runlog.stage_summary(STAGE, reused=reused_all, generated=rendered_all, note=note)
    facts = {
        "outputs": outputs,
        "shot_sources": sources,
        "clips_used": sorted(s for s, kind in sources.items() if kind == "clip"),
        "kenburns_used": sorted(s for s, kind in sources.items() if kind == "kenburns"),
        "missing_pictures": sorted(s for s, kind in sources.items() if kind == "missing"),
        "subtitle_cues": cue_count,
        "audio": audio_facts,
        "segments_reused": len(reused_all),
        "segments_rendered": len(rendered_all),
    }
    (FINAL / "assembly.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    return facts
