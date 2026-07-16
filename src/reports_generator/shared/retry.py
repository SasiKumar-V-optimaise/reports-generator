"""Bounded retry support with injectable sleeping for deterministic tests."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")
Sleep = Callable[[float], None]
RetryObserver = Callable[[int, BaseException, float], None]


@dataclass(frozen=True)
class RetryPolicy:
    """A finite exponential-backoff policy.

    ``max_attempts`` includes the initial call.  A policy of one therefore
    performs no retries.
    """

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float | None = None
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds cannot be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        if self.max_delay_seconds is not None and self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds cannot be negative")
        if not self.retry_exceptions:
            raise ValueError("retry_exceptions cannot be empty")

    def delay_after(self, failed_attempt: int) -> float:
        """Return the delay following a one-based failed attempt number."""

        if failed_attempt < 1:
            raise ValueError("failed_attempt must be at least 1")
        delay = self.initial_delay_seconds * (self.backoff_multiplier ** (failed_attempt - 1))
        if self.max_delay_seconds is not None:
            delay = min(delay, self.max_delay_seconds)
        return float(delay)


def retry_call(
    operation: Callable[P, T],
    *args: P.args,
    policy: RetryPolicy | None = None,
    sleep: Sleep = time.sleep,
    on_retry: RetryObserver | None = None,
    **kwargs: P.kwargs,
) -> T:
    """Call ``operation`` until it succeeds or ``policy`` is exhausted."""

    selected_policy = policy or RetryPolicy()
    for attempt in range(1, selected_policy.max_attempts + 1):
        try:
            return operation(*args, **kwargs)
        except selected_policy.retry_exceptions as exc:
            if attempt >= selected_policy.max_attempts:
                raise
            delay = selected_policy.delay_after(attempt)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            if delay > 0:
                sleep(delay)

    raise RuntimeError("unreachable retry state")


def retry(
    policy: RetryPolicy | None = None,
    *,
    sleep: Sleep = time.sleep,
    on_retry: RetryObserver | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorate a function with :func:`retry_call`."""

    selected_policy = policy or RetryPolicy()

    def decorate(operation: Callable[P, T]) -> Callable[P, T]:
        @wraps(operation)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            return retry_call(
                operation,
                *args,
                policy=selected_policy,
                sleep=sleep,
                on_retry=on_retry,
                **kwargs,
            )

        return wrapped

    return decorate
