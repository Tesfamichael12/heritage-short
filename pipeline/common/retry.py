"""Retries, and the difference between "try again" and "stop for today".

Providers fail in two ways that need opposite handling:

- Retryable: a per-minute rate limit, a 5xx, a timeout. Waiting and trying
  again usually works.
- QuotaExhausted: the daily allowance is gone. Trying again only wastes time,
  so the stage stops cleanly and reports what is left to do.
"""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class Retryable(Exception):
    """A failure worth retrying after a pause."""


class QuotaExhausted(Exception):
    """The provider's daily allowance is used up. Do not retry until it resets."""


class MissingKey(Exception):
    """A provider credential is not set in .env."""


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 60.0) -> float:
    """Exponential backoff with jitter: about 2 s, 4 s, 8 s ... capped."""
    return min(cap, base * (2 ** (attempt - 1))) * (0.5 + random.random() / 2)


def with_retries(
    call: Callable[[int], T],
    *,
    attempts: int = 4,
    base: float = 2.0,
    cap: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``call(attempt)`` until it succeeds or the attempts run out.

    Only ``Retryable`` is retried. ``QuotaExhausted`` and every other error
    pass straight through to the caller.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call(attempt)
        except Retryable as exc:
            last = exc
            if attempt == attempts:
                break
            delay = backoff_delay(attempt, base, cap)
            print(f"  retrying in {delay:.1f}s (attempt {attempt} of {attempts} failed: {exc})")
            sleep(delay)
    assert last is not None
    raise last
