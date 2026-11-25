"""Smoke test: call each provider once and log its latency to runs.jsonl.

Run this first. It tells you in a minute which accounts and keys work, before
any real generation is attempted. The image it makes is reused as the input
for the video calibration job.
"""
from __future__ import annotations

import time
from typing import Callable

from .common import config, runlog
from .common.retry import MissingKey, QuotaExhausted
from .providers import cloudflare, gemini, kaggle

TEXT_MODEL = "gemini-3.5-flash-lite"
SPEECH_MODEL = "gemini-3.8-flash-tts"
IMAGE_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
SMOKE_DIR = config.OUTPUTS / "smoke"

# Generic content only: nothing from the family story is sent by the smoke test.
SPEECH_TEXT = "ሰላም። ይህ የድምፅ ሙከራ ነው።"
IMAGE_PROMPT = (
    "an old brass oil lamp glowing on a wooden windowsill at dusk, subject centred, "
    "warm hand-painted gouache illustration, soft grain, golden-hour light"
)


def _text() -> str:
    reply = gemini.generate_text(TEXT_MODEL, "Reply with the single word: ready", stage="smoke", attempts=2)
    return f"replied {reply.strip()[:20]!r}"


def _speech() -> str:
    wav = gemini.synthesize(SPEECH_MODEL, SPEECH_TEXT, voice="Kore",
                            style_instruction="calm, warm", stage="smoke", attempts=2)
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    (SMOKE_DIR / "speech.wav").write_bytes(wav)
    return f"{gemini.wav_seconds(wav):.1f}s of audio -> outputs/smoke/speech.wav"


def _image() -> str:
    png = cloudflare.generate_image(IMAGE_MODEL, IMAGE_PROMPT, size=1024, seed=7, stage="smoke", attempts=2)
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    (SMOKE_DIR / "image.png").write_bytes(png)
    return f"{len(png) // 1024} KB image -> outputs/smoke/image.png"


def _kaggle() -> str:
    started = time.perf_counter()
    status, error = "ok", None
    try:
        return kaggle.check_auth()
    except Exception as exc:
        status, error = "error", f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        runlog.write({
            "event": "provider_check", "stage": "smoke", "provider": "kaggle",
            "model": None, "status": status, "error": error,
            "latency_s": round(time.perf_counter() - started, 3),
        })


CHECKS: list[tuple[str, Callable[[], str]]] = [
    (f"Gemini text    ({TEXT_MODEL})", _text),
    (f"Gemini speech  ({SPEECH_MODEL})", _speech),
    ("Cloudflare     (flux-2-klein-4b)", _image),
    ("Kaggle         (API sign-in)", _kaggle),
]


def main() -> int:
    failed = skipped = 0
    print("Smoke test: one call per provider\n")
    for label, check in CHECKS:
        started = time.perf_counter()
        try:
            detail = check()
            mark = "ok     "
        except MissingKey as exc:
            detail, mark = str(exc), "SKIPPED"
            skipped += 1
        except QuotaExhausted as exc:
            detail, mark = str(exc)[:160], "QUOTA  "
            failed += 1
        except Exception as exc:
            detail, mark = f"{type(exc).__name__}: {exc}"[:220], "FAILED "
            failed += 1
        print(f"  {mark} {label:36s} {time.perf_counter() - started:6.1f}s  {detail}")

    print()
    if failed:
        print(f"{failed} provider(s) failed. Every attempt is in runs.jsonl.")
        return 1
    if skipped:
        print(f"{skipped} provider(s) skipped: add the missing keys to .env (see .env.example).")
        return 1
    print("All providers answered. Latencies are in runs.jsonl.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
