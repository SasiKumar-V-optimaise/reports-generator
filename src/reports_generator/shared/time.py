"""Consistent date and clock helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol

OUTPUT_DATE_FORMAT = "%d-%m-%Y"


class Clock(Protocol):
    """Injectable clock used by workflows that need the current time."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC time."""


class SystemClock:
    """Production UTC clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def utc_now() -> datetime:
    """Return a timezone-aware current UTC timestamp."""

    return datetime.now(timezone.utc)


def format_output_date(value: date) -> str:
    """Format a production date using the public artifact convention."""

    return value.strftime(OUTPUT_DATE_FORMAT)


def parse_output_date(value: str) -> date:
    """Parse a strict ``DD-MM-YYYY`` production date."""

    try:
        return datetime.strptime(value, OUTPUT_DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError(f"Invalid production date {value!r}; expected DD-MM-YYYY") from exc
