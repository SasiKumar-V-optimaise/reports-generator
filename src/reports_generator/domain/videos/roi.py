"""ROI normalization, source-size inference, and scaling."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from math import isfinite

from .models import FrameSize, PixelPoint, Point, Roi

COMMON_ROI_SOURCE_SIZES: tuple[FrameSize, ...] = (
    FrameSize(1440, 1080),
    FrameSize(2620, 1216),
    FrameSize(1920, 1080),
    FrameSize(1280, 720),
)


def normalize_roi_points(points: Iterable[object]) -> tuple[Point, ...]:
    """Normalize YAML-style ``[x, y]`` and ``{x, y}`` points, skipping junk."""

    normalized: list[Point] = []
    for point in points:
        x: object
        y: object
        if isinstance(point, Mapping):
            x, y = point.get("x"), point.get("y")
        elif (
            isinstance(point, Sequence) and not isinstance(point, (str, bytes)) and len(point) >= 2
        ):
            x, y = point[0], point[1]
        else:
            continue
        try:
            converted = float(x), float(y)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if isfinite(converted[0]) and isfinite(converted[1]):
            normalized.append(converted)
    return tuple(normalized)


def scale_roi_points(
    points: Iterable[Point],
    output_width: int,
    output_height: int,
    source_width: int,
    source_height: int,
) -> tuple[PixelPoint, ...]:
    """Scale once into output pixels and clamp to valid pixel coordinates."""

    if min(output_width, output_height, source_width, source_height) <= 0:
        raise ValueError("Source and output dimensions must be greater than zero")
    scale_x = output_width / source_width
    scale_y = output_height / source_height
    return tuple(
        (
            min(max(int(round(x * scale_x)), 0), output_width - 1),
            min(max(int(round(y * scale_y)), 0), output_height - 1),
        )
        for x, y in points
    )


def scale_roi(roi: Roi, source_size: FrameSize, output_size: FrameSize) -> tuple[PixelPoint, ...]:
    return scale_roi_points(
        roi.points,
        output_size.width,
        output_size.height,
        source_size.width,
        source_size.height,
    )


def infer_roi_source_size(
    points: Iterable[Point],
    frame_size: FrameSize,
    common_sizes: Iterable[FrameSize] = COMMON_ROI_SOURCE_SIZES,
) -> FrameSize:
    """Preserve legacy inference when ROI coordinates exceed saved frames."""

    values = tuple(points)
    max_x = max((x for x, _y in values), default=0.0)
    max_y = max((y for _x, y in values), default=0.0)
    if max_x <= frame_size.width and max_y <= frame_size.height:
        return frame_size
    for candidate in common_sizes:
        if max_x <= candidate.width + 2 and max_y <= candidate.height + 2:
            if candidate != frame_size:
                return candidate
    inferred_width = (
        frame_size.width * 2 if max_x <= frame_size.width * 2 + 2 else int(round(max_x)) + 1
    )
    inferred_height = (
        frame_size.height * 2 if max_y <= frame_size.height * 2 + 2 else int(round(max_y)) + 1
    )
    return FrameSize(inferred_width, inferred_height)
