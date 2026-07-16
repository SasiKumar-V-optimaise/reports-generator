"""Gate detection geometry and coverage rules."""

from .coverage import (
    build_coverage_intervals,
    detection_inside_roi_percent,
    measure_frame_coverage,
    parse_yolo_detection,
    yolo_bbox_polygon,
)
from .geometry import (
    convex_polygon_intersection,
    point_in_polygon,
    point_on_segment,
    polygon_area,
    signed_area,
)
from .models import (
    CoverageInterval,
    CoverageStatus,
    FrameCoverage,
    FrameSize,
    Point,
    Polygon,
    YoloDetection,
)

__all__ = [
    "CoverageInterval",
    "CoverageStatus",
    "FrameCoverage",
    "FrameSize",
    "Point",
    "Polygon",
    "YoloDetection",
    "build_coverage_intervals",
    "convex_polygon_intersection",
    "detection_inside_roi_percent",
    "measure_frame_coverage",
    "parse_yolo_detection",
    "point_in_polygon",
    "point_on_segment",
    "polygon_area",
    "signed_area",
    "yolo_bbox_polygon",
]
