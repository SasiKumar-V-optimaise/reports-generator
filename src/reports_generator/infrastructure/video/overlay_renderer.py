"""OpenCV drawing primitives with no report-specific business rules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from .opencv_reader import Frame

Point = tuple[int, int]
Color = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class TextOverlay:
    text: str
    origin: Point
    color: Color = (255, 255, 255)
    scale: float = 0.6
    thickness: int = 2
    background_color: Color | None = None


@dataclass(frozen=True, slots=True)
class RectangleOverlay:
    top_left: Point
    bottom_right: Point
    color: Color = (255, 255, 255)
    thickness: int = 2
    label: str | None = None


BoxOverlay = RectangleOverlay


@dataclass(frozen=True, slots=True)
class PolygonOverlay:
    points: tuple[Point, ...]
    color: Color = (255, 255, 255)
    thickness: int = 2
    fill_color: Color | None = None
    fill_alpha: float = 0.0
    label: str | None = None

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("a polygon overlay requires at least two points")
        if not 0 <= self.fill_alpha <= 1:
            raise ValueError("fill_alpha must be between zero and one")


@dataclass(frozen=True, slots=True)
class OverlaySpec:
    polygons: tuple[PolygonOverlay, ...] = ()
    rectangles: tuple[RectangleOverlay, ...] = ()
    texts: tuple[TextOverlay, ...] = ()


class OverlayRenderer:
    """Render caller-selected primitives; colors and labels stay external."""

    def render(
        self,
        frame: Frame,
        spec: OverlaySpec | None = None,
        *,
        polygons: Sequence[PolygonOverlay] = (),
        rectangles: Sequence[RectangleOverlay] = (),
        texts: Sequence[TextOverlay] = (),
        copy: bool = True,
    ) -> Frame:
        if frame.dtype != np.uint8:
            raise ValueError("frame dtype must be uint8")
        output = frame.copy() if copy else frame
        selected = spec or OverlaySpec()

        for polygon in (*selected.polygons, *polygons):
            self._draw_polygon(output, polygon)
        for rectangle in (*selected.rectangles, *rectangles):
            cv2.rectangle(
                output,
                rectangle.top_left,
                rectangle.bottom_right,
                rectangle.color,
                rectangle.thickness,
            )
            if rectangle.label:
                self._draw_text(
                    output,
                    TextOverlay(
                        rectangle.label,
                        (rectangle.top_left[0], max(15, rectangle.top_left[1] - 5)),
                        rectangle.color,
                    ),
                )
        for text in (*selected.texts, *texts):
            self._draw_text(output, text)
        return output

    def render_in_place(self, frame: Frame, spec: OverlaySpec) -> Frame:
        return self.render(frame, spec, copy=False)

    def _draw_polygon(self, frame: Frame, polygon: PolygonOverlay) -> None:
        points = np.asarray(polygon.points, dtype=np.int32)
        if polygon.fill_color is not None and polygon.fill_alpha > 0 and len(points) >= 3:
            layer = frame.copy()
            cv2.fillPoly(layer, [points], polygon.fill_color)
            cv2.addWeighted(
                layer,
                polygon.fill_alpha,
                frame,
                1.0 - polygon.fill_alpha,
                0,
                frame,
            )
        cv2.polylines(
            frame,
            [points],
            isClosed=len(points) >= 3,
            color=polygon.color,
            thickness=polygon.thickness,
            lineType=cv2.LINE_AA,
        )
        if polygon.label:
            self._draw_text(frame, TextOverlay(polygon.label, polygon.points[0], polygon.color))

    @staticmethod
    def _draw_text(frame: Frame, text: TextOverlay) -> None:
        origin = text.origin
        if text.background_color is not None:
            (width, height), baseline = cv2.getTextSize(
                text.text,
                cv2.FONT_HERSHEY_SIMPLEX,
                text.scale,
                text.thickness,
            )
            cv2.rectangle(
                frame,
                (origin[0] - 2, origin[1] - height - 2),
                (origin[0] + width + 2, origin[1] + baseline + 2),
                text.background_color,
                -1,
            )
        cv2.putText(
            frame,
            text.text,
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            text.scale,
            text.color,
            text.thickness,
            cv2.LINE_AA,
        )


OpenCvOverlayRenderer = OverlayRenderer
OpenCVOverlayRenderer = OverlayRenderer
