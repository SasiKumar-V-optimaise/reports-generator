"""Generation and merging of compact video windows."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from .models import VideoWindow


def merge_labels(existing: str, new: str) -> str:
    parts = [part.strip() for part in f"{existing}, {new}".split(",") if part.strip()]
    return ", ".join(dict.fromkeys(parts))


def merge_video_windows(windows: Iterable[VideoWindow]) -> tuple[VideoWindow, ...]:
    """Merge overlapping or touching windows and deduplicate their labels."""

    ordered = sorted(windows, key=lambda item: (item.start, item.end, item.label))
    if not ordered:
        return ()
    merged: list[VideoWindow] = [ordered[0]]
    for window in ordered[1:]:
        current = merged[-1]
        if window.start <= current.end:
            merged[-1] = VideoWindow(
                start=current.start,
                end=max(current.end, window.end),
                label=merge_labels(current.label, window.label),
            )
        else:
            merged.append(window)
    return tuple(merged)


merge_windows = merge_video_windows


def build_origin_window(
    origin_time: datetime,
    *,
    pre_origin: timedelta = timedelta(seconds=60),
    duration: timedelta = timedelta(seconds=300),
    shift_start: datetime | None = None,
    shift_end: datetime | None = None,
    label: str = "",
) -> VideoWindow | None:
    """Build a missing-loadcell clip and clamp it to the shift window."""

    if pre_origin < timedelta(0):
        raise ValueError("pre_origin cannot be negative")
    if duration <= timedelta(0):
        raise ValueError("duration must be greater than zero")
    start = origin_time - pre_origin
    end = start + duration
    if shift_start is not None:
        start = max(start, shift_start)
    if shift_end is not None:
        end = min(end, shift_end)
    if end <= start:
        return None
    return VideoWindow(start=start, end=end, label=label)


def build_origin_windows(
    origins: Iterable[tuple[datetime, str]],
    *,
    pre_origin: timedelta = timedelta(seconds=60),
    duration: timedelta = timedelta(seconds=300),
    shift_start: datetime | None = None,
    shift_end: datetime | None = None,
) -> tuple[VideoWindow, ...]:
    built = (
        build_origin_window(
            origin,
            pre_origin=pre_origin,
            duration=duration,
            shift_start=shift_start,
            shift_end=shift_end,
            label=label,
        )
        for origin, label in origins
    )
    return merge_video_windows(window for window in built if window is not None)
