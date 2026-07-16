"""Streaming OpenCV video encoding."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import cv2
import numpy as np

from .opencv_reader import Frame


class OpenCvFrameWriter:
    """Encode frames incrementally to a caller-provided output path."""

    def __init__(
        self,
        output_path: Path,
        *,
        fps: float,
        frame_size: tuple[int, int],
        codec: str = "mp4v",
        is_color: bool = True,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be greater than zero")
        if len(codec) != 4:
            raise ValueError("codec must contain exactly four characters")
        width, height = frame_size
        if width <= 0 or height <= 0:
            raise ValueError("frame_size dimensions must be greater than zero")

        self.output_path = Path(output_path)
        self.fps = float(fps)
        self.frame_size = (int(width), int(height))
        self.codec = codec
        self.is_color = is_color
        self.frames_written = 0
        self._writer: cv2.VideoWriter | None = None
        self._closed = False

    @property
    def is_open(self) -> bool:
        return self._writer is not None and self._writer.isOpened()

    def open(self) -> OpenCvFrameWriter:
        if self._closed:
            raise RuntimeError("video writer has already been closed")
        if self.is_open:
            return self
        if not self.output_path.parent.is_dir():
            raise FileNotFoundError(f"video output directory not found: {self.output_path.parent}")
        writer = cv2.VideoWriter(
            str(self.output_path),
            cv2.VideoWriter_fourcc(*self.codec),
            self.fps,
            self.frame_size,
            self.is_color,
        )
        if not writer.isOpened():
            writer.release()
            raise RuntimeError(f"failed to open video output: {self.output_path}")
        self._writer = writer
        return self

    def write(self, frame: Frame) -> None:
        if self._closed:
            raise RuntimeError("cannot write to a closed video writer")
        self._validate_frame(frame)
        if not self.is_open:
            self.open()
        assert self._writer is not None
        self._writer.write(np.ascontiguousarray(frame))
        self.frames_written += 1

    def write_all(self, frames: Iterable[Frame]) -> int:
        for frame in frames:
            self.write(frame)
        return self.frames_written

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        self._closed = True

    def __enter__(self) -> OpenCvFrameWriter:
        return self.open()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _validate_frame(self, frame: Frame) -> None:
        if not isinstance(frame, np.ndarray):
            raise TypeError("frame must be a numpy array")
        if frame.dtype != np.uint8:
            raise ValueError("frame dtype must be uint8")
        expected_width, expected_height = self.frame_size
        if frame.shape[:2] != (expected_height, expected_width):
            raise ValueError(
                "frame dimensions do not match frame_size: "
                f"received {frame.shape[1]}x{frame.shape[0]}, "
                f"expected {expected_width}x{expected_height}"
            )
        if self.is_color and (frame.ndim != 3 or frame.shape[2] != 3):
            raise ValueError("color frames must have shape (height, width, 3)")
        if not self.is_color and frame.ndim != 2:
            raise ValueError("grayscale frames must have shape (height, width)")


OpenCVFrameWriter = OpenCvFrameWriter
OpenCvVideoWriter = OpenCvFrameWriter
