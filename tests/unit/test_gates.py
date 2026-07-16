from datetime import datetime, timedelta

import pytest

from reports_generator.domain.gates import (
    CoverageStatus,
    FrameCoverage,
    FrameSize,
    YoloDetection,
    build_coverage_intervals,
    convex_polygon_intersection,
    measure_frame_coverage,
    point_in_polygon,
    polygon_area,
)

ROI = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))


def test_polygon_clipping_and_boundary_membership() -> None:
    subject = ((5.0, 0.0), (15.0, 0.0), (15.0, 10.0), (5.0, 10.0))
    assert polygon_area(convex_polygon_intersection(subject, ROI)) == pytest.approx(50.0)
    assert point_in_polygon((0.0, 5.0), ROI)


def test_detection_coverage_uses_detection_area_denominator() -> None:
    frame = measure_frame_coverage(
        datetime(2026, 6, 30, 12),
        (YoloDetection(3, 0.5, 0.5, 1.0, 1.0),),
        ROI,
        FrameSize(20, 20),
    )
    assert frame.coverage_percent == pytest.approx(25.0)
    assert frame.detection_count == 1
    assert frame.centroid_inside_count == 1


def test_interval_averages_and_no_sample_policy() -> None:
    start = datetime(2026, 6, 30, 12)
    intervals = build_coverage_intervals(
        start,
        start + timedelta(minutes=20),
        (
            FrameCoverage(start + timedelta(minutes=1), 100.0, 1, 1),
            FrameCoverage(start + timedelta(minutes=5), 80.0, 1, 1),
        ),
        alert_on_no_samples=False,
    )
    assert intervals[0].average_coverage_percent == 90.0
    assert intervals[0].status is CoverageStatus.VIEW_UNCHANGED
    assert intervals[1].status is CoverageStatus.NO_SAMPLES
    assert not intervals[1].alert
