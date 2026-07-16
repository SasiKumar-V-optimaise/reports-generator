"""Immutable values for video-domain calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

Point = tuple[float, float]
PixelPoint = tuple[int, int]


@dataclass(frozen=True)
class FrameSize:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Frame dimensions must be greater than zero")


@dataclass(frozen=True)
class Roi:
    name: str
    points: tuple[Point, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ROI name cannot be empty")
        if len(self.points) < 2:
            raise ValueError("An ROI requires at least two points")


@dataclass(frozen=True)
class VideoWindow:
    start: datetime
    end: datetime
    label: str = ""

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("A video window must end after it starts")

    def contains(self, timestamp: datetime) -> bool:
        """Video frame selection preserves the legacy inclusive end."""

        return self.start <= timestamp <= self.end


@dataclass(frozen=True)
class FrameCandidate:
    timestamp: datetime
    identifier: str
    source_date: date | None = None


@dataclass(frozen=True)
class SelectedFrame:
    frame: FrameCandidate
    window_index: int
    window_count: int
    window_label: str


@dataclass(frozen=True)
class PipeCountEvent:
    timestamp: datetime
    count: int

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("Pipe count must be greater than zero")
