import pytest

from reports_generator.shared.retry import RetryPolicy, retry_call


def test_retry_succeeds_after_bounded_exponential_delays() -> None:
    attempts = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary")
        return "ok"

    result = retry_call(
        operation,
        policy=RetryPolicy(4, 0.5, 2.0, retry_exceptions=(OSError,)),
        sleep=sleeps.append,
    )
    assert result == "ok"
    assert attempts == 3
    assert sleeps == [0.5, 1.0]


def test_retry_reraises_final_error_without_final_sleep() -> None:
    sleeps: list[float] = []
    with pytest.raises(OSError, match="still broken"):
        retry_call(
            lambda: (_ for _ in ()).throw(OSError("still broken")),
            policy=RetryPolicy(max_attempts=2, initial_delay_seconds=1),
            sleep=sleeps.append,
        )
    assert sleeps == [1.0]


def test_non_retryable_error_is_not_caught() -> None:
    with pytest.raises(ValueError):
        retry_call(
            lambda: (_ for _ in ()).throw(ValueError("bad input")),
            policy=RetryPolicy(retry_exceptions=(OSError,)),
            sleep=lambda _delay: None,
        )
