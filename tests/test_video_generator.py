import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from reports.video.video_generator import ShiftVideoGenerator


class FakeVideoWriter:
    instances = []

    def __init__(self, *args, **kwargs):
        self.frames = []
        self.released = False
        self.__class__.instances.append(self)

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame)

    def release(self):
        self.released = True


class ShiftVideoGeneratorPipeCountTest(unittest.TestCase):
    def _generator(self, tmp, verified_path, frames):
        generator = object.__new__(ShiftVideoGenerator)
        generator.shift = "A"
        generator.caster_log_label = "test-caster"
        generator.output_path = Path(tmp) / "out.mp4"
        generator.video_cfg = {"fps": 10}
        generator.verified_report_path = verified_path
        generator.root = Path(tmp)
        generator._collect_images = lambda: frames
        generator._resolve_resolution = lambda w, h: (w, h)
        return generator

    def _run_generator(self, generator):
        draws = []
        image = np.zeros((80, 100, 3), dtype=np.uint8)
        FakeVideoWriter.instances = []

        def record_text(frame, text, org, font, scale, color, thickness, line_type):
            draws.append({
                "text": text,
                "org": org,
                "scale": scale,
                "color": color,
                "thickness": thickness,
                "line_type": line_type,
            })
            return frame

        with (
            patch("reports.video.video_generator.cv2.imread", return_value=image),
            patch("reports.video.video_generator.cv2.VideoWriter", FakeVideoWriter),
            patch("reports.video.video_generator.cv2.VideoWriter_fourcc", return_value=0),
            patch("reports.video.video_generator.cv2.putText", side_effect=record_text),
        ):
            output_path = generator.generate()

        return output_path, draws, FakeVideoWriter.instances[0]

    def test_pipe_count_overlay_follows_verified_origin_times(self):
        with TemporaryDirectory() as tmp:
            verified_path = Path(tmp) / "verified.csv"
            verified_path.write_text(
                "\n".join([
                    "Pipe Number,Origin Time",
                    "2,15-07-2026 06:02:51",
                    "1,15-07-2026 06:00:51",
                    "3,15-07-2026 06:09:39",
                ]),
                encoding="utf-8",
            )
            frames = [
                "frame_15-07-2026-06-00-50.jpeg",
                "frame_15-07-2026-06-00-51.jpeg",
                "frame_15-07-2026-06-05-00.jpeg",
                "frame_15-07-2026-06-10-00.jpeg",
            ]
            generator = self._generator(tmp, verified_path, frames)

            output_path, draws, writer = self._run_generator(generator)

        self.assertEqual(output_path, str(Path(tmp) / "out.mp4"))
        self.assertEqual(len(writer.frames), 4)
        self.assertTrue(writer.released)
        self.assertEqual(
            [draw["text"] for draw in draws],
            [
                "2026-07-15 06:00:50",
                "2026-07-15 06:00:51",
                "Pipe Count: 1",
                "2026-07-15 06:05:00",
                "Pipe Count: 2",
                "2026-07-15 06:10:00",
                "Pipe Count: 3",
            ],
        )

        timestamp_draws = [draw for draw in draws if not draw["text"].startswith("Pipe Count")]
        self.assertTrue(all(draw["org"] == (20, 60) for draw in timestamp_draws))
        self.assertTrue(all(draw["scale"] == 0.7 for draw in timestamp_draws))
        self.assertTrue(all(draw["color"] == (0, 255, 255) for draw in timestamp_draws))
        self.assertTrue(all(draw["thickness"] == 2 for draw in timestamp_draws))

        pipe_draws = [draw for draw in draws if draw["text"].startswith("Pipe Count")]
        self.assertEqual([draw["org"] for draw in pipe_draws], [(20, 35), (20, 35), (20, 35)])

    def test_invalid_verified_report_data_does_not_block_video_generation(self):
        with TemporaryDirectory() as tmp:
            verified_path = Path(tmp) / "verified.csv"
            verified_path.write_text(
                "\n".join([
                    "Pipe Number,Origin Time",
                    ",",
                    "bad,not-a-date",
                ]),
                encoding="utf-8",
            )
            frames = [
                "frame_15-07-2026-06-00-51.jpeg",
                "frame_15-07-2026-06-02-51.jpeg",
            ]
            generator = self._generator(tmp, verified_path, frames)

            _output_path, draws, writer = self._run_generator(generator)

        self.assertEqual(len(writer.frames), 2)
        self.assertEqual(
            [draw["text"] for draw in draws],
            [
                "2026-07-15 06:00:51",
                "2026-07-15 06:02:51",
            ],
        )


if __name__ == "__main__":
    unittest.main()
