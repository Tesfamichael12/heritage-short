"""Cloudflare Workers AI: keyframe images with FLUX.2 klein.

klein takes multipart form data and up to four reference images, each of
which must be smaller than 512 by 512 pixels. Every call is logged to
runs.jsonl, one line per attempt.
"""
from __future__ import annotations

import base64
import io
import math
from pathlib import Path

import requests
from PIL import Image

from ..common import config, runlog
from ..common.retry import MissingKey, QuotaExhausted, Retryable, with_retries

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
MAX_REFERENCE_SIDE = 511
DAILY_QUOTA_CODE = 3036

# Published price for flux-2-klein-4b, in neurons per 512x512 tile.
NEURONS_PER_OUTPUT_TILE = 26.05
NEURONS_PER_INPUT_TILE = 5.37


def has_key() -> bool:
    return bool(config.env("CF_ACCOUNT_ID") and config.env("CF_API_TOKEN"))


def estimate_neurons(width: int, height: int, reference_sizes: list[tuple[int, int]]) -> float:
    """Estimated cost of one klein-4b image from Cloudflare's published per-tile price."""
    def tiles(w: int, h: int) -> int:
        return math.ceil(w / 512) * math.ceil(h / 512)

    cost = tiles(width, height) * NEURONS_PER_OUTPUT_TILE
    cost += sum(tiles(w, h) for w, h in reference_sizes) * NEURONS_PER_INPUT_TILE
    return round(cost, 2)


def _reference_png(path: Path) -> tuple[bytes, tuple[int, int]]:
    """Shrink a reference image below Cloudflare's 512 pixel limit."""
    image = Image.open(path).convert("RGB")
    image.thumbnail((MAX_REFERENCE_SIDE, MAX_REFERENCE_SIDE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue(), image.size


def _image_bytes(response: requests.Response) -> bytes:
    """The API answers with raw image bytes or with JSON holding base64."""
    if response.headers.get("content-type", "").startswith("image/"):
        return response.content
    body = response.json()
    payload = body.get("result") or body
    return base64.b64decode(payload["image"])


def _as_png(data: bytes) -> bytes:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def _raise_for(response: requests.Response) -> None:
    if response.status_code < 400:
        return
    text = response.text[:400]
    codes: list[int] = []
    try:
        codes = [e.get("code") for e in response.json().get("errors", [])]
    except ValueError:
        pass
    if response.status_code == 429:
        if DAILY_QUOTA_CODE in codes or "daily free allocation" in text:
            raise QuotaExhausted(f"Cloudflare daily neuron allowance used up: {text}")
        raise Retryable(f"Cloudflare rate limit: {text}")
    if response.status_code in (408, 500, 502, 503, 504):
        raise Retryable(f"Cloudflare {response.status_code}: {text}")
    raise RuntimeError(f"Cloudflare {response.status_code}: {text}")


def generate_image(
    model: str,
    prompt: str,
    *,
    size: int,
    seed: int,
    references: list[Path] | None = None,
    stage: str,
    shot: str | None = None,
    cache_key: str | None = None,
    attempts: int = 4,
) -> bytes:
    """Generate one square image, optionally conditioned on reference images. Returns PNG bytes."""
    account, token = config.env("CF_ACCOUNT_ID"), config.env("CF_API_TOKEN")
    if not (account and token):
        raise MissingKey("CF_ACCOUNT_ID and CF_API_TOKEN are not set in .env")

    references = list(references or [])[:4]
    prepared = [_reference_png(path) for path in references]
    neurons = estimate_neurons(size, size, [dims for _, dims in prepared])

    def call(attempt: int) -> bytes:
        fields: dict[str, tuple] = {
            "prompt": (None, prompt),
            "width": (None, str(size)),
            "height": (None, str(size)),
            "seed": (None, str(seed)),
        }
        for index, (png, _) in enumerate(prepared):
            fields[f"input_image_{index}"] = (f"ref{index}.png", png, "image/png")

        with runlog.model_call(
            stage=stage, provider="cloudflare", model=model, shot=shot,
            params={"width": size, "height": size, "references": len(prepared)},
            seed=seed, prompt=prompt, cache_key=cache_key, attempt=attempt,
            inputs={f"reference_{i}": config.rel(p) for i, p in enumerate(references)},
        ) as rec:
            rec["cost"] = {"unit": "neurons", "amount": neurons, "estimated": True}
            try:
                response = requests.post(
                    API.format(account=account, model=model),
                    headers={"Authorization": f"Bearer {token}"},
                    files=fields, timeout=180,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                raise Retryable(f"Cloudflare network error: {exc}") from exc
            rec["http_status"] = response.status_code
            _raise_for(response)
            return _as_png(_image_bytes(response))

    return with_retries(call, attempts=attempts)
