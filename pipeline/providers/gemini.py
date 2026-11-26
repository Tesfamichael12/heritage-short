"""Gemini API: text (script, storyboard, translation) and speech (narration).

Every call is logged to runs.jsonl, one line per attempt.
"""
from __future__ import annotations

import base64
import io
import time
import wave
from typing import Any

from google import genai
from google.genai import _interactions as interactions_api
from google.genai import errors, types

from ..common import config, runlog
from ..common.retry import MissingKey, QuotaExhausted, Retryable, with_retries

SAMPLE_RATE = 24000  # Gemini speech output: 24 kHz, mono, 16-bit

# Free-tier limits read from this project's rate-limit dashboard on 26 November 2026
# (Google does not publish them). Requests per minute and per day, per model.
LIMITS: dict[str, dict[str, int]] = {
    "gemini-3.8-flash-tts": {"rpm": 3, "rpd": 10},
    "gemini-3.8-flash-lite-tts": {"rpm": 3, "rpd": 10},
    "gemini-3.8-flash": {"rpm": 5, "rpd": 20},
    "gemini-3.5-flash-lite": {"rpm": 15, "rpd": 500},
}
PACE_DIR = config.ROOT / ".cache" / "pace"


def _pace(model: str, sleep: Any = time.sleep) -> None:
    """Wait until this model's per-minute limit allows another request.

    The time of each request is kept in a file, so separate runs started in
    quick succession also respect the limit. A request rejected for the
    per-minute limit may still count against the daily one, so we wait instead.
    """
    rpm = LIMITS.get(model, {}).get("rpm")
    if not rpm:
        return
    interval = 60.0 / rpm + 1.0
    PACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = PACE_DIR / model
    try:
        last = float(stamp.read_text())
    except (OSError, ValueError):
        last = 0.0
    wait = last + interval - time.time()
    if wait > 0:
        print(f"  waiting {wait:.0f}s for {model}'s limit of {rpm} requests a minute")
        sleep(wait)
    stamp.write_text(f"{time.time():.3f}")


def _client() -> genai.Client:
    key = config.env("GEMINI_API_KEY")
    if not key:
        raise MissingKey("GEMINI_API_KEY is not set in .env")
    return genai.Client(api_key=key)


def has_key() -> bool:
    return config.env("GEMINI_API_KEY") is not None


def _classify(exc: errors.APIError) -> Exception:
    """Turn an API error into Retryable, QuotaExhausted, or leave it as it is."""
    code = getattr(exc, "code", None)
    text = f"{exc} {getattr(exc, 'details', '')}"
    if code == 429:
        if "PerDay" in text or "per day" in text.lower() or "daily" in text.lower():
            return QuotaExhausted(f"Gemini daily quota used up: {str(exc)[:300]}")
        return Retryable(f"Gemini rate limit: {str(exc)[:200]}")
    if code in (500, 502, 503, 504):
        return Retryable(f"Gemini server error {code}: {str(exc)[:200]}")
    return exc


def _usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    return {
        "unit": "tokens",
        "input": getattr(usage, "prompt_token_count", None),
        "output": getattr(usage, "candidates_token_count", None),
        "total": getattr(usage, "total_token_count", None),
    }


def generate_text(
    model: str,
    prompt: str,
    *,
    stage: str,
    json_mode: bool = False,
    temperature: float | None = None,
    shot: str | None = None,
    attempts: int = 4,
) -> str:
    """One text completion. With json_mode the model is asked for JSON only."""
    client = _client()
    cfg: dict[str, Any] = {}
    if json_mode:
        cfg["response_mime_type"] = "application/json"
    if temperature is not None:
        cfg["temperature"] = temperature

    def call(attempt: int) -> str:
        _pace(model)
        with runlog.model_call(
            stage=stage, provider="gemini", model=model, shot=shot,
            params={"json_mode": json_mode, "temperature": temperature},
            prompt=prompt, attempt=attempt,
        ) as rec:
            try:
                response = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(**cfg) if cfg else None,
                )
            except errors.APIError as exc:
                raise _classify(exc) from exc
            rec["cost"] = _usage(response)
            text = response.text or ""
            rec["output_chars"] = len(text)
            if not text.strip():
                raise Retryable("Gemini returned an empty response")
            return text

    return with_retries(call, attempts=attempts)


def _to_wav(data: bytes) -> bytes:
    """Gemini returns either a WAV file or raw PCM. Always hand back a WAV file."""
    if data[:4] == b"RIFF":
        return data
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(data)
    return buffer.getvalue()


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def speech_prompt(text: str, style_instruction: str | None) -> str:
    """A readable record of what the speech model is asked for, used in the log and cache keys.

    The 3.8 speech models take the line verbatim and the style as a separate
    annotation, so this string is not what is sent; see _speech_request.
    """
    text = text.strip()
    if style_instruction and style_instruction.strip():
        return f"[style: {style_instruction.strip()}]\n{text}"
    return text


def _speech_request(model: str, text: str, voice: str, style_instruction: str | None) -> dict[str, Any]:
    """The Interactions API body for single-speaker speech (gemini-3.8-*-tts)."""
    item: dict[str, Any] = {"type": "text", "text": text.strip()}
    if style_instruction and style_instruction.strip():
        item["annotations"] = [{"type": "speech_metadata", "style": style_instruction.strip()}]
    return {
        "model": model,
        "input": [{"type": "user_input", "content": [item]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }


def _classify_status(exc: Exception) -> Exception:
    """Same classification as _classify, for the Interactions API's own error types."""
    code = getattr(exc, "status_code", None)
    text = str(exc)
    if code == 429:
        if "PerDay" in text or "per day" in text.lower() or "daily" in text.lower():
            return QuotaExhausted(f"Gemini daily quota used up: {text[:300]}")
        return Retryable(f"Gemini rate limit: {text[:200]}")
    if code is None or code >= 500:  # connection errors and timeouts carry no status code
        return Retryable(f"Gemini speech error {code}: {text[:200]}")
    return exc


def _plain(value: Any) -> Any:
    if value is None:
        return None
    dump = getattr(value, "model_dump", None)
    return dump(exclude_none=True) if dump else value


def synthesize(
    model: str,
    text: str,
    *,
    voice: str,
    style_instruction: str | None,
    stage: str,
    shot: str | None = None,
    cache_key: str | None = None,
    attempts: int = 3,
) -> bytes:
    """Turn one piece of text into speech. Returns a WAV file as bytes."""
    key = config.env("GEMINI_API_KEY")
    if not key:
        raise MissingKey("GEMINI_API_KEY is not set in .env")
    client = genai.Client(api_key=key, http_options={"api_version": "v1beta", "timeout": 180_000})  # ms; see FAILURES.md F9
    prompt = speech_prompt(text, style_instruction)
    body = _speech_request(model, text, voice, style_instruction)

    def call(attempt: int) -> bytes:
        _pace(model)
        with runlog.model_call(
            stage=stage, provider="gemini", model=model, shot=shot,
            params={"voice": voice, "style_instruction": style_instruction},
            prompt=prompt, cache_key=cache_key, attempt=attempt,
        ) as rec:
            try:
                interaction = client.interactions.create(**body)
            except interactions_api.APIError as exc:
                raise _classify_status(exc) from exc
            usage = _plain(getattr(interaction, "usage", None))
            rec["cost"] = {"unit": "tokens", "raw": usage, **_interaction_tokens(usage)}
            audio = getattr(interaction, "output_audio", None)
            data = getattr(audio, "data", None)
            if not data:
                raise Retryable("Gemini speech returned no audio")
            wav = _to_wav(base64.b64decode(data) if isinstance(data, str) else data)
            rec["audio_s"] = round(wav_seconds(wav), 3)
            return wav

    return with_retries(call, attempts=attempts)


def _interaction_tokens(usage: Any) -> dict[str, Any]:
    """Pick input and output token counts out of the usage record, whatever it calls them."""
    if not isinstance(usage, dict):
        return {"input": None, "output": None}
    def find(*names: str) -> Any:
        for name in names:
            if usage.get(name) is not None:
                return usage[name]
        return None
    return {
        "input": find("total_input_tokens", "input_tokens", "prompt_token_count"),
        "output": find("total_output_tokens", "output_tokens", "candidates_token_count"),
    }
