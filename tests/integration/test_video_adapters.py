from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from reports_generator.infrastructure.video import (
    OpenCvFrameReader,
    OpenCvFrameWriter,
    OverlayRenderer,
    OverlaySpec,
    PolygonOverlay,
    RectangleOverlay,
)


def test_opencv_writer_and_reader_stream_frames(tmp_path: Path) -> None:
    output = tmp_path / "stream.avi"
    frames = tuple(np.full((24, 32, 3), fill_value=value, dtype=np.uint8) for value in (0, 60, 120))

    with OpenCvFrameWriter(
        output,
        fps=5,
        frame_size=(32, 24),
        codec="MJPG",
    ) as writer:
        assert writer.write_all(iter(frames)) == 3

    reader = OpenCvFrameReader(output)
    decoded = list(reader)
    metadata = reader.metadata()

    assert len(decoded) == 3
    assert decoded[0].shape == (24, 32, 3)
    assert metadata.width == 32
    assert metadata.height == 24
    assert metadata.frame_count == 3


def test_writer_requires_the_central_builder_to_create_directories(tmp_path: Path) -> None:
    writer = OpenCvFrameWriter(
        tmp_path / "missing" / "video.avi",
        fps=1,
        frame_size=(8, 8),
        codec="MJPG",
    )
    with pytest.raises(FileNotFoundError, match="output directory"):
        writer.open()
    assert not (tmp_path / "missing").exists()


def test_overlay_renderer_uses_plain_presentation_inputs_without_mutating_source() -> None:
    source = np.zeros((40, 40, 3), dtype=np.uint8)
    spec = OverlaySpec(
        polygons=(
            PolygonOverlay(
                points=((10, 10), (30, 10), (30, 30), (10, 30)),
                color=(0, 0, 255),
                fill_color=(0, 0, 200),
                fill_alpha=1.0,
            ),
        ),
        rectangles=(RectangleOverlay((2, 2), (7, 7), color=(0, 255, 0)),),
    )

    rendered = OverlayRenderer().render(source, spec)

    assert not source.any()
    assert rendered[20, 20, 2] == 200
    assert rendered[2, 2, 1] > 0
