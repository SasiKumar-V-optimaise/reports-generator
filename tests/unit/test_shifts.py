from datetime import date, datetime

import pytest

from reports_generator.domain.shifts import (
    Shift,
    calculate_shift_window,
    resolve_production_date,
    shift_at,
)


@pytest.mark.parametrize(
    ("shift", "start", "end"),
    [
        (Shift.A, datetime(2026, 7, 14, 6), datetime(2026, 7, 14, 14)),
        (Shift.B, datetime(2026, 7, 14, 14), datetime(2026, 7, 14, 22)),
        (Shift.C, datetime(2026, 7, 14, 22), datetime(2026, 7, 15, 6)),
    ],
)
def test_shift_windows(shift: Shift, start: datetime, end: datetime) -> None:
    window = calculate_shift_window(date(2026, 7, 14), shift)
    assert (window.start, window.end) == (start, end)


def test_early_morning_shift_c_uses_previous_production_date() -> None:
    value = datetime(2026, 7, 15, 5, 59, 59)
    assert shift_at(value) is Shift.C
    assert resolve_production_date(value) == date(2026, 7, 14)


def test_shift_end_is_exclusive() -> None:
    assert shift_at(datetime(2026, 7, 14, 14)) is Shift.B
