"""Streaming video input, output, and presentation-only overlays."""

from .opencv_reader import (
    Frame,
    OpenCVFrameReader,
    OpenCvFrameReader,
    OpenCvVideoReader,
    VideoMetadata,
)
from .opencv_writer import (
    OpenCVFrameWriter,
    OpenCvFrameWriter,
    OpenCvVideoWriter,
)
from .overlay_renderer import (
    BoxOverlay,
    Color,
    OpenCVOverlayRenderer,
    OpenCvOverlayRenderer,
    OverlayRenderer,
    OverlaySpec,
    Point,
    PolygonOverlay,
    RectangleOverlay,
    TextOverlay,
)

__all__ = [
    "BoxOverlay",
    "Color",
    "Frame",
    "OpenCVFrameReader",
    "OpenCVFrameWriter",
    "OpenCVOverlayRenderer",
    "OpenCvFrameReader",
    "OpenCvFrameWriter",
    "OpenCvOverlayRenderer",
    "OpenCvVideoReader",
    "OpenCvVideoWriter",
    "OverlayRenderer",
    "OverlaySpec",
    "Point",
    "PolygonOverlay",
    "RectangleOverlay",
    "TextOverlay",
    "VideoMetadata",
]
