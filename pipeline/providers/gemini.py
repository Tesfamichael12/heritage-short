"""Gemini API: text (script, storyboard, translation) and speech (narration).

Every call is logged to runs.jsonl, one line per attempt.
"""
from __future__ import annotations

import io
import wave
from typing import Any

from google import genai
from google.genai import errors, types

from ..common import config, runlog
from ..common.retry import MissingKey, QuotaExhausted, Retryable, with_retries

SAMPLE_RATE = 24000  # Gemini speech output: 24 kHz, mono, 16-bit


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
    """The text sent to the speech model: an optional style instruction, then the line."""
    text = text.strip()
    if style_instruction and style_instruction.strip():
        return f"Read aloud in a {style_instruction.strip()} voice. Speak only the text after the colon:\n{text}"
    return text


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
    client = _client()
    prompt = speech_prompt(text, style_instruction)

    def call(attempt: int) -> bytes:
        with runlog.model_call(
            stage=stage, provider="gemini", model=model, shot=shot,
            params={"voice": voice, "style_instruction": style_instruction},
            prompt=prompt, cache_key=cache_key, attempt=attempt,
        ) as rec:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                            )
                        ),
                    ),
                )
            except errors.APIError as exc:
                raise _classify(exc) from exc

            rec["cost"] = _usage(response)
            try:
                part = response.candidates[0].content.parts[0]
                data = part.inline_data.data
            except (AttributeError, IndexError, TypeError) as exc:
                raise Retryable("Gemini speech returned no audio") from exc
            if not data:
                raise Retryable("Gemini speech returned empty audio")
            wav = _to_wav(data)
            rec["audio_s"] = round(wav_seconds(wav), 3)
            return wav

    return with_retries(call, attempts=attempts)
