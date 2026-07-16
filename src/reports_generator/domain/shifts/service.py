"""Pure shift-window and production-date calculations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from .models import Shift, ShiftDefinition, ShiftWindow

DEFAULT_SHIFT_DEFINITIONS: tuple[ShiftDefinition, ...] = (
    ShiftDefinition(Shift.A, time(6, 0), time(14, 0)),
    ShiftDefinition(Shift.B, time(14, 0), time(22, 0)),
    ShiftDefinition(Shift.C, time(22, 0), time(6, 0)),
)


def _definition_for(
    shift: Shift,
    definitions: Iterable[ShiftDefinition],
) -> ShiftDefinition:
    matches = tuple(item for item in definitions if item.shift is shift)
    if not matches:
        raise ValueError(f"No definition configured for shift {shift.value}")
    if len(matches) > 1:
        raise ValueError(f"Multiple definitions configured for shift {shift.value}")
    return matches[0]


def calculate_shift_window(
    production_date: date,
    shift: Shift | str,
    definitions: Iterable[ShiftDefinition] = DEFAULT_SHIFT_DEFINITIONS,
) -> ShiftWindow:
    """Build a concrete window, rolling its end into the following day."""

    selected_shift = Shift.parse(shift)
    definition = _definition_for(selected_shift, definitions)
    start = datetime.combine(production_date, definition.start)
    end = datetime.combine(production_date, definition.end)
    if end <= start:
        end += timedelta(days=1)
    return ShiftWindow(production_date, selected_shift, start, end)


# A concise alias used by application services.
shift_window = calculate_shift_window


def resolve_shift_window(
    value: datetime,
    definitions: Iterable[ShiftDefinition] = DEFAULT_SHIFT_DEFINITIONS,
) -> ShiftWindow:
    """Resolve the shift and production date containing ``value``."""

    configured = tuple(definitions)
    for candidate_date in (value.date(), value.date() - timedelta(days=1)):
        for definition in configured:
            window = calculate_shift_window(candidate_date, definition.shift, configured)
            if window.contains(value):
                return window
    raise ValueError(f"No configured shift contains {value.isoformat()}")


def shift_at(
    value: datetime,
    definitions: Iterable[ShiftDefinition] = DEFAULT_SHIFT_DEFINITIONS,
) -> Shift:
    """Return the shift active at ``value``."""

    return resolve_shift_window(value, definitions).shift


def resolve_production_date(
    value: datetime,
    shift: Shift | str | None = None,
    definitions: Iterable[ShiftDefinition] = DEFAULT_SHIFT_DEFINITIONS,
) -> date:
    """Resolve the reporting date for a timestamp.

    Supplying ``shift`` validates that the timestamp actually belongs to that
    shift.  This prevents an early-morning Shift C record from being assigned
    to the calendar day on which it happened.
    """

    configured = tuple(definitions)
    if shift is None:
        return resolve_shift_window(value, configured).production_date

    selected_shift = Shift.parse(shift)
    for candidate_date in (value.date(), value.date() - timedelta(days=1)):
        window = calculate_shift_window(candidate_date, selected_shift, configured)
        if window.contains(value):
            return candidate_date
    raise ValueError(
        f"Timestamp {value.isoformat()} is outside configured shift {selected_shift.value}"
    )
