"""Typed values for gate geometry and monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

Point = tuple[float, float]


@dataclass(frozen=True)
class Polygon:
    points: tuple[Point, ...]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("A polygon requires at least three points")
        if any(not (isfinite(x) and isfinite(y)) for x, y in self.points):
            raise ValueError("Polygon coordinates must be finite")


@dataclass(frozen=True)
class FrameSize:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Frame dimensions must be greater than zero")


@dataclass(frozen=True)
class YoloDetection:
    class_id: int
    x_center: float
    y_center: float
    width: float
    height: float

    @property
    def values_are_finite(self) -> bool:
        return all(
            isfinite(value) for value in (self.x_center, self.y_center, self.width, self.height)
        )


@dataclass(frozen=True)
class FrameCoverage:
    timestamp: datetime
    coverage_percent: float
    detection_count: int
    centroid_inside_count: int
    centroid_x_min: float | None = None
    centroid_x_max: float | None = None
    centroid_y_min: float | None = None
    centroid_y_max: float | None = None

    @property
    def gate2_detection_count(self) -> int:
        return self.detection_count


class CoverageStatus(str, Enum):
    VIEW_UNCHANGED = "VIEW_UNCHANGED"
    POSSIBLE_VIEW_CHANGE = "POSSIBLE_VIEW_CHANGE"
    NO_SAMPLES = "NO_SAMPLES"


@dataclass(frozen=True)
class CoverageInterval:
    start: datetime
    end: datetime
    sample_count: int
    detection_count: int
    centroid_inside_count: int
    average_coverage_percent: float
    threshold_percent: float
    status: CoverageStatus
    alert: bool
    centroid_x_min: float | None = None
    centroid_x_max: float | None = None
    centroid_y_min: float | None = None
    centroid_y_max: float | None = None

    @property
    def avg_coverage_percent(self) -> float:
        return self.average_coverage_percent

    @property
    def avg_detection_inside_roi_percent(self) -> float:
        return self.average_coverage_percent

    @property
    def gate2_detection_count(self) -> int:
        return self.detection_count
