"""Run the cheap experiments in EXPERIMENTS.md and write their measurements.

    python -m pipeline.experiments E4 E5 E6 E10 E11 E12 E1 E2

Each experiment writes to outputs/experiments/<id>_*/ and a results.json there.
Model calls are tagged with the experiment id in runs.jsonl. Nothing here
touches the film's own outputs. EXPERIMENTS.md is written by hand from the
results.json files, so a reader can check every number against them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter

from . import assemble, keyframes, radio
from .common import config
from .providers import cloudflare, gemini

EXP = config.OUTPUTS / "experiments"


def _board() -> dict[str, Any]:
    return json.loads(config.STORYBOARD.read_text(encoding="utf-8"))


def _shot(board: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in board["shots"] if s["id"] == sid)


def _save(folder: Path, results: dict[str, Any]) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False)[:2500])
    return results


def _image(board: dict[str, Any], prompt: str, seed: int, refs: list[Path], *, size: int | None = None,
           shot: str | None = None) -> bytes:
    settings = board["keyframes"]
    last: Exception | None = None
    for attempt in range(3):  # the safety filter sometimes rejects a harmless output (FAILURES.md F7)
        try:
            return cloudflare.generate_image(settings["model"], prompt, size=size or settings["size"],
                                             seed=seed + attempt * 1000, references=refs or None,
                                             stage="experiment", shot=shot, attempts=2)
        except Exception as exc:  # noqa: BLE001 - recorded in runs.jsonl by the provider
            last = exc
    raise RuntimeError(f"image failed three times: {last}")


def _colour_stats(path: Path) -> dict[str, float]:
    """Mean saturation, brightness and hue spread: a rough numeric fingerprint of the look."""
    hsv = np.asarray(Image.open(path).convert("RGB").resize((256, 256)).convert("HSV"), dtype=np.float64) / 255.0
    return {"mean_saturation": round(float(hsv[..., 1].mean()), 4),
            "mean_brightness": round(float(hsv[..., 2].mean()), 4),
            "hue_std": round(float(hsv[..., 0].std()), 4)}


def _spread(values: list[float]) -> float:
    return round(float(np.std(values)), 4)


# --- E4: with and without the reference image --------------------------------

def e4() -> dict[str, Any]:
    os.environ["EXPERIMENT"] = "E4"
    board, folder = _board(), EXP / "E4_reference_image"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid in ("s02", "s04", "s06"):
        shot = _shot(board, sid)
        prompt = keyframes.shot_prompt(board, shot)
        with_ref = folder / f"{sid}_with_reference.png"
        with_ref.write_bytes(keyframes.keyframe_path(sid).read_bytes())  # the film's own keyframe
        without = folder / f"{sid}_without_reference.png"
        without.write_bytes(_image(board, prompt, shot["keyframe"]["seed"], [], shot=sid))
        rows.append({"shot": sid, "with_reference": config.rel(with_ref), "without_reference": config.rel(without),
                     "neurons_with": round(cloudflare.estimate_neurons(1024, 1024, [(511, 511)]), 1),
                     "neurons_without": round(cloudflare.estimate_neurons(1024, 1024, []), 1)})
    _contact([Path(config.ROOT / r[k]) for r in rows for k in ("with_reference", "without_reference")],
             folder / "comparison.jpg", columns=2)
    return _save(folder, {"experiment": "E4", "same_prompt_and_seed": True, "rows": rows,
                          "how_to_read": "comparison.jpg: left column with the reference, right column without; one row per shot"})


def _contact(paths: list[Path], target: Path, columns: int, side: int = 384) -> None:
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (side * columns, side * rows), "white")
    for i, path in enumerate(paths):
        image = Image.open(path).convert("RGB")
        image.thumbnail((side, side))
        sheet.paste(image, ((i % columns) * side, (i // columns) * side))
    sheet.save(target, quality=88)


# --- E5: fixed style block against paraphrased style ---------------------------

PARAPHRASES = [
    "soft watercolour-like painting with a grainy paper feel, warm golden morning light in the Ethiopian highlands, earthy yellows and greens",
    "hand-painted illustration in gentle gouache, sunlit highland colours, ochre, olive and blue tones, simple shapes",
    "storybook painting, matte paint texture, glowing highland sunlight, muted warm palette with soft blues",
]


def e5() -> dict[str, Any]:
    os.environ["EXPERIMENT"] = "E5"
    board, folder = _board(), EXP / "E5_style_block"
    folder.mkdir(parents=True, exist_ok=True)
    fixed, para = [], []
    for sid, paraphrase in zip(("s01", "s07", "s08"), PARAPHRASES):
        shot = _shot(board, sid)
        fixed_path = folder / f"{sid}_fixed.png"
        fixed_path.write_bytes(keyframes.keyframe_path(sid).read_bytes())  # made with the fixed block
        prompt = f"{shot['keyframe']['prompt'].strip().rstrip('.')}. {paraphrase}. {board['style']['negative']}"
        para_path = folder / f"{sid}_paraphrased.png"
        para_path.write_bytes(_image(board, prompt, shot["keyframe"]["seed"], [], shot=sid))
        fixed.append(fixed_path)
        para.append(para_path)
    stats = {"fixed": {p.name: _colour_stats(p) for p in fixed}, "paraphrased": {p.name: _colour_stats(p) for p in para}}
    spread = {group: {metric: _spread([s[metric] for s in stats[group].values()])
                      for metric in ("mean_saturation", "mean_brightness", "hue_std")} for group in stats}
    _contact(fixed + para, folder / "comparison.jpg", columns=3)
    return _save(folder, {"experiment": "E5", "paraphrases": PARAPHRASES, "stats": stats,
                          "spread_across_three_shots": spread,
                          "how_to_read": "comparison.jpg: top row fixed style block, bottom row a different paraphrase per shot. "
                                         "A smaller spread means the three shots look more alike."})


# --- E6: keyframe size -----------------------------------------------------------

def _sharpness(path: Path, crop_to: tuple[int, int] = (1080, 1920)) -> float:
    """Edge energy of the vertical crop after scaling it to 1080x1920, as the film does."""
    image = Image.open(path).convert("L")
    w, h = image.size
    cw = round(h * crop_to[0] / crop_to[1])
    image = image.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h)).resize(crop_to, Image.LANCZOS)
    edges = np.asarray(image.filter(ImageFilter.FIND_EDGES), dtype=np.float64)
    return round(float(edges.var()), 2)


def e6() -> dict[str, Any]:
    os.environ["EXPERIMENT"] = "E6"
    board, folder = _board(), EXP / "E6_keyframe_size"
    folder.mkdir(parents=True, exist_ok=True)
    shot = _shot(board, "s08")
    prompt = keyframes.shot_prompt(board, shot)
    small = folder / "s08_1024.png"
    small.write_bytes(keyframes.keyframe_path("s08").read_bytes())
    large = folder / "s08_1440.png"
    large.write_bytes(_image(board, prompt, shot["keyframe"]["seed"], [], size=1440, shot="s08"))
    return _save(folder, {"experiment": "E6", "rows": [
        {"size": 1024, "neurons": round(cloudflare.estimate_neurons(1024, 1024, []), 1), "vertical_crop_width": 576,
         "upscale_to_1080": round(1080 / 576, 2), "edge_variance_at_1080x1920": _sharpness(small)},
        {"size": 1440, "neurons": round(cloudflare.estimate_neurons(1440, 1440, []), 1), "vertical_crop_width": 810,
         "upscale_to_1080": round(1080 / 810, 2), "edge_variance_at_1080x1920": _sharpness(large)},
    ], "note": "Edge variance is higher when the picture holds more fine detail after enlarging. Same prompt and seed."})


# --- E10: ducking attack ---------------------------------------------------------

def _ffmpeg(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-y", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:])
    return result.stderr


def _rms_windows(wav: Path, windows: list[tuple[float, float]]) -> float:
    """Mean RMS level in dBFS of a mono 48 kHz WAV over the given windows."""
    import wave
    with wave.open(str(wav), "rb") as f:
        rate = f.getframerate()
        data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    levels = []
    for start, end in windows:
        chunk = data[int(start * rate):int(end * rate)]
        if len(chunk):
            levels.append(20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-9))
    return round(float(np.mean(levels)), 2)


def e10() -> dict[str, Any]:
    os.environ["EXPERIMENT"] = "E10"
    board, folder = _board(), EXP / "E10_ducking"
    folder.mkdir(parents=True, exist_ok=True)
    timeline = json.loads(config.TIMELINE.read_text(encoding="utf-8"))
    starts = [(s["narration_start_s"], s["narration_s"]) for s in timeline["shots"]]
    total = timeline["total_s"]
    # voice track: every line placed on the timeline, as the assembly stage does
    inputs, parts = [], []
    for i, (start, _) in enumerate(starts):
        inputs += ["-i", str(config.OUTPUTS / "narration" / f"s{i + 1:02d}.wav")]
        parts.append(f"[{i}:a]aresample=48000,adelay={int(start * 1000)}[v{i}]")
    n = len(starts)
    music = config.ROOT / ".cache" / "audio" / "placeholder_music.wav"
    graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(n)) + \
        f"amix=inputs={n}:normalize=0,apad=whole_dur={total},pan=mono|c0=c0[voice]"
    voice = folder / "voice.wav"
    _ffmpeg([*inputs, "-filter_complex", graph, "-map", "[voice]", "-t", f"{total}", "-ar", "48000", "-c:a", "pcm_s16le", str(voice)], folder)
    duck = board["mix"]["duck"]
    onsets = [(start, start + 0.3) for start, _ in starts]           # first 300 ms of each line
    held = [(start + 1.0, start + dur - 0.2) for start, dur in starts]  # the middle of each line
    gaps = [(starts[i][0] + starts[i][1] + 0.4, starts[i + 1][0] - 0.1) for i in range(n - 1)
            if starts[i + 1][0] - 0.1 > starts[i][0] + starts[i][1] + 0.4]
    rows = []
    for attack in (300, 50):
        out = folder / f"music_ducked_attack{attack}.wav"
        _ffmpeg(["-i", str(music), "-i", str(voice), "-filter_complex",
                 f"[0:a]aresample=48000,pan=mono|c0=c0,atrim=0:{total}[m];[1:a]asplit[k][drop];[drop]anullsink;"
                 f"[m][k]sidechaincompress=threshold={duck['threshold']}:ratio={duck['ratio']}:attack={attack}:release={duck['release_ms']}[d]",
                 "-map", "[d]", "-ar", "48000", "-c:a", "pcm_s16le", str(out)], folder)
        rows.append({"attack_ms": attack,
                     "music_dbfs_first_300ms_of_lines": _rms_windows(out, onsets),
                     "music_dbfs_mid_line": _rms_windows(out, held),
                     "music_dbfs_in_pauses": _rms_windows(out, gaps)})
    undocked = _rms_windows(music if music.suffix == ".wav" else music, [(0, total)])
    return _save(folder, {"experiment": "E10", "music": "placeholder drone (the generated score was not ready)",
                          "voice_dbfs_mid_line": _rms_windows(voice, held), "rows": rows,
                          "how_to_read": "Lower music level at line openings means the first syllable is less masked. "
                                         "The gap between mid-line and pause levels is the depth of the duck."})


# --- E11: one-pass against two-pass loudness -----------------------------------

def _ebur128(path: Path) -> dict[str, float]:
    err = _ffmpeg(["-nostats", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"], path.parent)
    summary = err[err.rfind("Summary:"):]
    def grab(label: str) -> float:
        line = next(l for l in summary.splitlines() if l.strip().startswith(label))
        return float(line.split(":")[1].split()[0])
    return {"integrated_lufs": grab("I:"), "true_peak_dbfs": grab("Peak:"), "lra_lu": grab("LRA:")}


def e11() -> dict[str, Any]:
    os.environ["EXPERIMENT"] = "E11"
    board, folder = _board(), EXP / "E11_loudness_passes"
    folder.mkdir(parents=True, exist_ok=True)
    voice = EXP / "E10_ducking" / "voice.wav"
    music = EXP / "E10_ducking" / "music_ducked_attack300.wav"
    if not voice.exists():
        e10()
    premix = folder / "premix.wav"
    _ffmpeg(["-i", str(voice), "-i", str(music), "-filter_complex",
             "[1:a]volume=-6dB[m];[0:a][m]amix=inputs=2:normalize=0", "-ar", "48000", "-c:a", "pcm_s24le", str(premix)], folder)
    target, tp = board["mix"]["target_lufs"], board["mix"]["true_peak_db"] - assemble.AAC_HEADROOM_DB
    one = folder / "one_pass.wav"
    _ffmpeg(["-i", str(premix), "-af", f"loudnorm=I={target}:TP={tp}:LRA=11", "-ar", "48000", "-c:a", "pcm_s24le", str(one)], folder)
    first = assemble.measure_loudness(premix) if hasattr(assemble, "measure_loudness") else None
    two = folder / "two_pass.wav"
    err = _ffmpeg(["-i", str(premix), "-af",
                   f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={first['input_i']}:measured_TP={first['input_tp']}"
                   f":measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}:offset={first['target_offset']}"
                   ":linear=true:print_format=json", "-ar", "48000", "-c:a", "pcm_s24le", str(two)], folder)
    import re
    mode = json.loads(re.findall(r"\{[^{}]*\}", err, flags=re.S)[-1]).get("normalization_type")
    rows = {"premix": _ebur128(premix), "one_pass": _ebur128(one), "two_pass": _ebur128(two)}
    for name in ("one_pass", "two_pass"):
        rows[name]["error_from_target_lu"] = round(rows[name]["integrated_lufs"] - target, 2)
    return _save(folder, {"experiment": "E11", "target_lufs": target, "true_peak_target": tp,
                          "two_pass_mode_reported": mode, "measured_with": "ffmpeg ebur128 (a different filter from loudnorm)",
                          "rows": rows})


# --- E12: zoompan wobble on a real keyframe -------------------------------------

def _shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Sub-pixel translation between two frames by phase correlation (parabolic peak fit)."""
    fa, fb = np.fft.fft2(a), np.fft.fft2(b)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-12
    corr = np.fft.ifft2(r).real
    y, x = np.unravel_index(np.argmax(corr), corr.shape)
    def refine(c_m, c_0, c_p):
        d = c_m - 2 * c_0 + c_p
        return 0.0 if d == 0 else 0.5 * (c_m - c_p) / d
    h, w = corr.shape
    dy = y + refine(corr[(y - 1) % h, x], corr[y, x], corr[(y + 1) % h, x])
    dx = x + refine(corr[y, (x - 1) % w], corr[y, x], corr[y, (x + 1) % w])
    return (dy - h if dy > h / 2 else dy), (dx - w if dx > w / 2 else dx)


def e12() -> dict[str, Any]:
    os.environ["EXPERIMENT"] = "E12"
    folder = EXP / "E12_zoompan_wobble"
    folder.mkdir(parents=True, exist_ok=True)
    still = keyframes.keyframe_path("s04")
    frames, out_w, out_h = 120, 1080, 1920
    w, h, x, y = assemble.crop_box(1024, 1024, out_w, out_h)
    rows = []
    for prescale in (1, 3):
        target = folder / f"prescale{prescale}"
        target.mkdir(exist_ok=True)
        chain = (f"crop={w}:{h}:{x}:{y},scale={out_w * prescale}:{out_h * prescale}:flags=lanczos,"
                 + assemble.zoompan(frames, out_w, out_h, 1.0, 1.1) + ",scale=270:480,format=gray")
        _ffmpeg(["-i", str(still), "-vf", chain, "-frames:v", str(frames), str(target / "f%03d.png")], folder)
        imgs = [np.asarray(Image.open(p), dtype=np.float64) for p in sorted(target.glob("f*.png"))]
        # The zoom is centred, so the centre of the picture should not move. Track a central patch.
        cy, cx = imgs[0].shape[0] // 2, imgs[0].shape[1] // 2
        patch = lambda im: im[cy - 48:cy + 48, cx - 48:cx + 48]  # noqa: E731
        shifts = [_shift(patch(imgs[i]), patch(imgs[i + 1])) for i in range(len(imgs) - 1)]
        dy = np.array([s[0] for s in shifts]) * (out_h / 480)  # back to output pixels
        dx = np.array([s[1] for s in shifts]) * (out_w / 270)
        rows.append({"prescale": prescale, "frames": len(imgs),
                     "centre_jitter_std_px": round(float(np.sqrt(dx.std() ** 2 + dy.std() ** 2)), 3),
                     "max_step_px": round(float(np.max(np.hypot(dx, dy))), 3),
                     "backward_steps": int(np.sum(np.diff(np.cumsum(dx)) < -0.25) + np.sum(np.diff(np.cumsum(dy)) < -0.25))})
        for p in target.glob("f*.png"):
            p.unlink()
        target.rmdir()
    return _save(folder, {"experiment": "E12", "still": config.rel(still), "move": "zoom 1.00 to 1.10 over 120 frames, centred",
                          "measure": "frame-to-frame shift of a central patch by phase correlation, in output pixels", "rows": rows})


# --- E1 and E2: speech ---------------------------------------------------------

def e1() -> dict[str, Any]:
    """One single take of every line against the eight per-line calls the film used."""
    os.environ["EXPERIMENT"] = "E1"
    board, folder = _board(), EXP / "E1_single_take"
    folder.mkdir(parents=True, exist_ok=True)
    n = board["narration"]
    wav = gemini.synthesize(n["model"], radio.take_text(board), voice=n["voice"],
                            style_instruction=n["style_instruction"], stage="experiment")
    (folder / "single_take.wav").write_bytes(wav)
    timeline = json.loads(config.TIMELINE.read_text(encoding="utf-8"))
    per_line = [s["narration_s"] for s in timeline["shots"]]
    chars = [len(_shot(board, s["id"])["narration"]["text"]) for s in timeline["shots"]]
    rates = [round(c / d, 2) for c, d in zip(chars, per_line)]
    return _save(folder, {"experiment": "E1", "model": n["model"], "voice": n["voice"],
                          "single_take_s": round(gemini.wav_seconds(wav), 2), "calls_single_take": 1,
                          "per_line_total_s": round(sum(per_line), 2), "calls_per_line": len(per_line),
                          "per_line_chars_per_s": rates, "per_line_rate_spread": _spread(rates),
                          "listen": ["outputs/experiments/E1_single_take/single_take.wav", "outputs/narration/s01.wav ... s08.wav"]})


def e2() -> dict[str, Any]:
    os.environ["EXPERIMENT"] = "E2"
    board, folder = _board(), EXP / "E2_style_instruction"
    folder.mkdir(parents=True, exist_ok=True)
    n, shot = board["narration"], _shot(board, "s07")
    wav = gemini.synthesize(n["model"], shot["narration"]["text"], voice=n["voice"], style_instruction=None,
                            stage="experiment", shot="s07")
    (folder / "s07_no_style.wav").write_bytes(wav)
    with_style = config.OUTPUTS / "narration" / "s07.wav"
    (folder / "s07_with_style.wav").write_bytes(with_style.read_bytes())
    return _save(folder, {"experiment": "E2", "line": shot["narration"]["text"], "style": n["style_instruction"],
                          "with_style_s": round(gemini.wav_seconds(with_style.read_bytes()), 2),
                          "no_style_s": round(gemini.wav_seconds(wav), 2)})


EXPERIMENTS: dict[str, Callable[[], dict[str, Any]]] = {
    "E1": e1, "E2": e2, "E4": e4, "E5": e5, "E6": e6, "E10": e10, "E11": e11, "E12": e12,
}


def main(argv: list[str]) -> int:
    failed = []
    for name in argv or list(EXPERIMENTS):
        print(f"\n=== {name} ===")
        try:
            EXPERIMENTS[name.upper()]()
        except Exception as exc:  # noqa: BLE001 - keep going; report at the end
            print(f"{name} failed: {type(exc).__name__}: {exc}")
            failed.append(name)
    if failed:
        print(f"\nFailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
