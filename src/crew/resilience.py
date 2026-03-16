"""Retry policy and circuit breaker for LLM API calls."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CircuitOpenError(Exception):
    """Raised when the circuit breaker is in OPEN state."""


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

# Retry on transient / rate-limit errors only.
_RETRYABLE = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)

# Never retry authentication or bad-request errors.
_NON_RETRYABLE = (
    anthropic.AuthenticationError,
    anthropic.BadRequestError,
)


class RetryPolicy:
    """Wraps a sync callable with exponential-backoff retries.

    Parameters
    ----------
    max_retries : int
        Maximum number of retry attempts (not counting the initial call).
    backoff_base : float
        Base for exponential delay: ``backoff_base ** attempt`` seconds.
    """

    def __init__(self, max_retries: int = 3, backoff_base: float = 2.0) -> None:
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    async def execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call *fn* with retries.  Sleeps between attempts using asyncio."""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except _NON_RETRYABLE:
                raise  # never retry
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = self.backoff_base ** attempt
                    logger.warning(
                        "Retryable error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1, self.max_retries + 1, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "All %d attempts exhausted: %s",
                        self.max_retries + 1, exc,
                    )
        raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-agent circuit breaker.

    States: CLOSED → (threshold consecutive failures) → OPEN
            → (reset_seconds elapsed) → HALF_OPEN
            → (probe success) → CLOSED  |  (probe failure) → OPEN

    Parameters
    ----------
    threshold : int
        Number of consecutive failures before opening the circuit.
    reset_seconds : int
        Seconds after which an OPEN circuit transitions to HALF_OPEN.
    """

    def __init__(self, threshold: int = 5, reset_seconds: int = 300) -> None:
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        """Return current state, accounting for OPEN → HALF_OPEN timeout."""
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self.reset_seconds
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def check(self) -> None:
        """Raise :class:`CircuitOpenError` if the circuit is OPEN."""
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker OPEN after {self.threshold} consecutive failures. "
                f"Resets in "
                f"{self.reset_seconds - (time.monotonic() - self._last_failure_time):.0f}s."
            )

    def record_success(self) -> None:
        """Record a successful call — reset failure count and close the circuit."""
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call.  Opens the circuit when the threshold is reached."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker OPENED after %d consecutive failures",
                self._failure_count,
            )
