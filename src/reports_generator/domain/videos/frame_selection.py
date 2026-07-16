"""Frame-name parsing, deterministic selection, and pipe-count lookup."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable
from datetime import datetime

from .models import FrameCandidate, PipeCountEvent, SelectedFrame, VideoWindow

_FRAME_TIMESTAMP = re.compile(
    r"(?<!\d)(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})-(\d{2})(?:-(\d{1,6}))?(?!\d)"
)


def parse_frame_timestamp(identifier: str) -> datetime | None:
    """Parse the final ``DD-MM-YYYY-HH-MM-SS[-fraction]`` token."""

    matches = tuple(_FRAME_TIMESTAMP.finditer(str(identifier)))
    if not matches:
        return None
    day, month, year, hour, minute, second, fraction = matches[-1].groups()
    microsecond = int((fraction or "0").ljust(6, "0"))
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            microsecond,
        )
    except ValueError:
        return None


frame_timestamp = parse_frame_timestamp


def _prefer(candidate: FrameCandidate, existing: FrameCandidate) -> bool:
    candidate_matches = candidate.source_date == candidate.timestamp.date()
    existing_matches = existing.source_date == existing.timestamp.date()
    if candidate_matches != existing_matches:
        return candidate_matches
    return candidate.identifier < existing.identifier


def select_frames(
    frames: Iterable[FrameCandidate],
    windows: Iterable[VideoWindow],
) -> tuple[SelectedFrame, ...]:
    """Select, order, and timestamp-deduplicate frames in requested windows."""

    selected_windows = tuple(sorted(windows, key=lambda item: (item.start, item.end)))
    by_timestamp: dict[datetime, SelectedFrame] = {}
    for frame in frames:
        for index, window in enumerate(selected_windows):
            if not window.contains(frame.timestamp):
                continue
            selected = SelectedFrame(
                frame=frame,
                window_index=index,
                window_count=len(selected_windows),
                window_label=window.label,
            )
            existing = by_timestamp.get(frame.timestamp)
            if existing is None or _prefer(frame, existing.frame):
                by_timestamp[frame.timestamp] = selected
            break
    return tuple(by_timestamp[key] for key in sorted(by_timestamp))


def count_frames(
    frames: Iterable[FrameCandidate],
    windows: Iterable[VideoWindow],
) -> int:
    return len(select_frames(frames, windows))


def pipe_count_for_frame(
    frame_time: datetime | None,
    events: Iterable[PipeCountEvent],
) -> int | None:
    """Return the last known positive pipe count at a frame timestamp."""

    if frame_time is None:
        return None
    ordered = sorted(events, key=lambda item: (item.timestamp, item.count))
    if not ordered:
        return None
    timestamps = [item.timestamp for item in ordered]
    index = bisect_right(timestamps, frame_time) - 1
    return None if index < 0 else ordered[index].count


select_pipe_count = pipe_count_for_frame
