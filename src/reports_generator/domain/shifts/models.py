"""Immutable production-shift values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum


class Shift(str, Enum):
    """The three production shifts."""

    A = "A"
    B = "B"
    C = "C"

    @classmethod
    def parse(cls, value: Shift | str) -> Shift:
        """Accept ``A`` and legacy ``shift_a`` spellings."""

        if isinstance(value, cls):
            return value
        normalized = str(value).strip()
        if normalized.lower().startswith("shift_"):
            normalized = normalized[6:]
        try:
            return cls(normalized.upper())
        except ValueError as exc:
            raise ValueError(f"Invalid shift {value!r}; expected A, B, or C") from exc

    @property
    def label(self) -> str:
        return f"shift_{self.value}"


@dataclass(frozen=True)
class ShiftDefinition:
    """Daily clock times defining a shift."""

    shift: Shift
    start: time
    end: time


@dataclass(frozen=True)
class ShiftWindow:
    """A concrete half-open shift interval for a production date."""

    production_date: date
    shift: Shift
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("A shift window must end after it starts")

    def contains(self, value: datetime) -> bool:
        """Return whether ``value`` is in ``[start, end)``."""

        return self.start <= value < self.end

    @property
    def duration_seconds(self) -> int:
        return int((self.end - self.start).total_seconds())
