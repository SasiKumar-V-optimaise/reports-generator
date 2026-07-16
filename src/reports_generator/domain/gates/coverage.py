"""Gate-2 coverage measurement and interval aggregation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from math import ceil

from .geometry import EPSILON, convex_polygon_intersection, point_in_polygon, polygon_area
from .models import (
    CoverageInterval,
    CoverageStatus,
    FrameCoverage,
    FrameSize,
    Point,
    YoloDetection,
)


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def parse_yolo_detection(line: str) -> YoloDetection | None:
    """Parse one YOLO line, ignoring optional confidence/trailing columns."""

    parts = line.strip().split()
    if len(parts) < 5:
        return None
    try:
        detection = YoloDetection(
            class_id=int(float(parts[0])),
            x_center=float(parts[1]),
            y_center=float(parts[2]),
            width=float(parts[3]),
            height=float(parts[4]),
        )
    except ValueError:
        return None
    return detection if detection.values_are_finite else None


def yolo_bbox_polygon(
    detection: YoloDetection,
    frame_size: FrameSize,
) -> tuple[Point, ...]:
    """Convert a normalized YOLO box into a frame-clipped polygon."""

    if not detection.values_are_finite:
        return ()
    x1 = _clamp(
        (detection.x_center - detection.width / 2.0) * frame_size.width,
        0.0,
        float(frame_size.width),
    )
    y1 = _clamp(
        (detection.y_center - detection.height / 2.0) * frame_size.height,
        0.0,
        float(frame_size.height),
    )
    x2 = _clamp(
        (detection.x_center + detection.width / 2.0) * frame_size.width,
        0.0,
        float(frame_size.width),
    )
    y2 = _clamp(
        (detection.y_center + detection.height / 2.0) * frame_size.height,
        0.0,
        float(frame_size.height),
    )
    if x2 <= x1 or y2 <= y1:
        return ()
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def detection_inside_roi_percent(
    detection_polygon: Sequence[Point],
    roi_polygon: Sequence[Point],
) -> float:
    """Return detected-box area inside the ROI, using box area as denominator."""

    detection_area = polygon_area(detection_polygon)
    if detection_area <= EPSILON:
        return 0.0
    intersection = convex_polygon_intersection(detection_polygon, roi_polygon)
    if not intersection:
        return 0.0
    return min(polygon_area(intersection) / detection_area * 100.0, 100.0)


def measure_frame_coverage(
    timestamp: datetime,
    detections: Iterable[YoloDetection],
    roi_polygon: Sequence[Point],
    frame_size: FrameSize,
    *,
    gate2_class_id: int = 3,
) -> FrameCoverage:
    """Measure the best valid Gate-2 detection for a frame."""

    if len(roi_polygon) < 3 or polygon_area(roi_polygon) <= EPSILON:
        raise ValueError("roi_polygon must have a positive area")
    best_coverage = 0.0
    detection_count = 0
    inside_count = 0
    centroids: list[Point] = []
    for detection in detections:
        if detection.class_id != gate2_class_id:
            continue
        polygon = yolo_bbox_polygon(detection, frame_size)
        if not polygon:
            continue
        detection_count += 1
        centroid = (
            detection.x_center * frame_size.width,
            detection.y_center * frame_size.height,
        )
        centroids.append(centroid)
        if point_in_polygon(centroid, roi_polygon):
            inside_count += 1
        best_coverage = max(
            best_coverage,
            detection_inside_roi_percent(polygon, roi_polygon),
        )

    xs = tuple(point[0] for point in centroids)
    ys = tuple(point[1] for point in centroids)
    return FrameCoverage(
        timestamp=timestamp,
        coverage_percent=best_coverage,
        detection_count=detection_count,
        centroid_inside_count=inside_count,
        centroid_x_min=min(xs) if xs else None,
        centroid_x_max=max(xs) if xs else None,
        centroid_y_min=min(ys) if ys else None,
        centroid_y_max=max(ys) if ys else None,
    )


def _optional_min(values: Iterable[float | None]) -> float | None:
    present = tuple(item for item in values if item is not None)
    return min(present) if present else None


def _optional_max(values: Iterable[float | None]) -> float | None:
    present = tuple(item for item in values if item is not None)
    return max(present) if present else None


def build_coverage_intervals(
    start: datetime,
    end: datetime,
    frames: Iterable[FrameCoverage],
    *,
    interval: timedelta = timedelta(minutes=10),
    threshold_percent: float = 80.0,
    alert_on_no_samples: bool = True,
) -> tuple[CoverageInterval, ...]:
    """Aggregate frame coverage over half-open monitoring intervals."""

    if end <= start:
        raise ValueError("Coverage window must end after it starts")
    if interval <= timedelta(0):
        raise ValueError("interval must be greater than zero")
    if not 0.0 <= threshold_percent <= 100.0:
        raise ValueError("threshold_percent must be between 0 and 100")

    interval_seconds = interval.total_seconds()
    count = ceil((end - start).total_seconds() / interval_seconds)
    buckets: list[list[FrameCoverage]] = [[] for _ in range(count)]
    for frame in frames:
        if not start <= frame.timestamp < end:
            continue
        index = int((frame.timestamp - start).total_seconds() // interval_seconds)
        buckets[index].append(frame)

    results: list[CoverageInterval] = []
    for index, bucket in enumerate(buckets):
        bucket_start = start + interval * index
        bucket_end = min(bucket_start + interval, end)
        sample_count = len(bucket)
        average = (
            sum(frame.coverage_percent for frame in bucket) / sample_count if sample_count else 0.0
        )
        if not sample_count:
            status = CoverageStatus.NO_SAMPLES
            alert = alert_on_no_samples
        elif average >= threshold_percent:
            status = CoverageStatus.VIEW_UNCHANGED
            alert = False
        else:
            status = CoverageStatus.POSSIBLE_VIEW_CHANGE
            alert = True
        results.append(
            CoverageInterval(
                start=bucket_start,
                end=bucket_end,
                sample_count=sample_count,
                detection_count=sum(frame.detection_count for frame in bucket),
                centroid_inside_count=sum(frame.centroid_inside_count for frame in bucket),
                average_coverage_percent=round(average, 2),
                threshold_percent=round(threshold_percent, 2),
                status=status,
                alert=alert,
                centroid_x_min=_optional_min(frame.centroid_x_min for frame in bucket),
                centroid_x_max=_optional_max(frame.centroid_x_max for frame in bucket),
                centroid_y_min=_optional_min(frame.centroid_y_min for frame in bucket),
                centroid_y_max=_optional_max(frame.centroid_y_max for frame in bucket),
            )
        )
    return tuple(results)


# Short compatibility aliases for adapters migrating from the legacy class.
measure_coverage = measure_frame_coverage
coverage_intervals = build_coverage_intervals
