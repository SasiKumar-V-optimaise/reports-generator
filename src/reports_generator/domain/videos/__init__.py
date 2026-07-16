"""Pure video window, ROI, and frame-selection rules."""

from .frame_selection import (
    count_frames,
    parse_frame_timestamp,
    pipe_count_for_frame,
    select_frames,
)
from .models import (
    FrameCandidate,
    FrameSize,
    PipeCountEvent,
    Roi,
    SelectedFrame,
    VideoWindow,
)
from .roi import infer_roi_source_size, normalize_roi_points, scale_roi, scale_roi_points
from .windows import build_origin_window, merge_labels, merge_video_windows

__all__ = [
    "FrameCandidate",
    "FrameSize",
    "PipeCountEvent",
    "Roi",
    "SelectedFrame",
    "VideoWindow",
    "build_origin_window",
    "count_frames",
    "infer_roi_source_size",
    "merge_labels",
    "merge_video_windows",
    "normalize_roi_points",
    "parse_frame_timestamp",
    "pipe_count_for_frame",
    "scale_roi",
    "scale_roi_points",
    "select_frames",
]
