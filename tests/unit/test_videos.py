from datetime import date, datetime, timedelta

from reports_generator.domain.videos import (
    FrameCandidate,
    FrameSize,
    PipeCountEvent,
    VideoWindow,
    infer_roi_source_size,
    merge_video_windows,
    normalize_roi_points,
    parse_frame_timestamp,
    pipe_count_for_frame,
    scale_roi_points,
    select_frames,
)


def test_windows_merge_touching_ranges_and_labels() -> None:
    start = datetime(2026, 1, 1, 22)
    merged = merge_video_windows(
        (
            VideoWindow(start + timedelta(seconds=10), start + timedelta(seconds=30), "pipe-2"),
            VideoWindow(start, start + timedelta(seconds=10), "pipe-1"),
        )
    )
    assert merged == (VideoWindow(start, start + timedelta(seconds=30), "pipe-1, pipe-2"),)


def test_roi_normalize_infer_scale_and_clamp() -> None:
    points = normalize_roi_points(([0, 0], {"x": 1309, "y": 598}, ["bad"]))
    assert points == ((0.0, 0.0), (1309.0, 598.0))
    assert scale_roi_points((*points, (1500.0, -5.0)), 1280, 720, 1310, 599) == (
        (0, 0),
        (1279, 719),
        (1279, 0),
    )
    source = infer_roi_source_size(((56.0, 784.0),), FrameSize(1310, 608))
    assert source == FrameSize(1440, 1080)


def test_frame_timestamp_selection_deduplication_and_count() -> None:
    start = datetime(2026, 1, 1, 23, 59, 58)
    midnight = datetime(2026, 1, 2)
    assert parse_frame_timestamp("frame_02-01-2026-00-00-00-667.jpeg") == midnight.replace(
        microsecond=667000
    )
    frames = (
        FrameCandidate(midnight, "copied", date(2026, 1, 1)),
        FrameCandidate(midnight, "native", date(2026, 1, 2)),
    )
    selected = select_frames(frames, (VideoWindow(start, midnight),))
    assert selected[0].frame.identifier == "native"
    events = (
        PipeCountEvent(start, 1),
        PipeCountEvent(midnight, 2),
    )
    assert pipe_count_for_frame(start - timedelta(seconds=1), events) is None
    assert pipe_count_for_frame(midnight, events) == 2
