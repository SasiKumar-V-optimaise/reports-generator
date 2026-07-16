"""Streaming OpenCV video-frame input."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

Frame = NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration_seconds(self) -> float | None:
        return self.frame_count / self.fps if self.fps > 0 else None


class OpenCvFrameReader:
    """Yield decoded frames one at a time and release the capture reliably."""

    def __init__(self, input_path: Path) -> None:
        self.input_path = Path(input_path)

    def iter_frames(self) -> Iterator[Frame]:
        capture = self._open_capture()
        try:
            while True:
                readable, frame = capture.read()
                if not readable:
                    break
                yield frame
        finally:
            capture.release()

    def frames(self) -> Iterator[Frame]:
        return self.iter_frames()

    def read(self) -> Iterator[Frame]:
        return self.iter_frames()

    def __iter__(self) -> Iterator[Frame]:
        return self.iter_frames()

    def metadata(self) -> VideoMetadata:
        capture = self._open_capture()
        try:
            return VideoMetadata(
                width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                fps=float(capture.get(cv2.CAP_PROP_FPS)),
                frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            )
        finally:
            capture.release()

    @property
    def info(self) -> VideoMetadata:
        return self.metadata()

    def _open_capture(self) -> cv2.VideoCapture:
        if not self.input_path.is_file():
            raise FileNotFoundError(f"video input not found: {self.input_path}")
        capture = cv2.VideoCapture(str(self.input_path))
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"failed to open video input: {self.input_path}")
        return capture


OpenCVFrameReader = OpenCvFrameReader
OpenCvVideoReader = OpenCvFrameReader
