from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from reports.video.source_cleanup import cleanup_shift_sources, shift_source_dirs


def _touch(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sample", encoding="utf-8")


class ShiftSourceCleanupTest(TestCase):
    def test_c_shift_deletes_exact_image_text_files_and_prunes_empty_old_date_folder(self):
        with TemporaryDirectory() as tmp:
            history = Path(tmp) / "history"
            old_img = history / "2026_07_13" / "Shift_C_img" / "frame_13.jpeg"
            old_text = history / "2026_07_13" / "Shift_C_text" / "frame_13.txt"
            next_img = history / "2026_07_14" / "Shift_C_img" / "frame_14.jpeg"
            next_text = history / "2026_07_14" / "Shift_C_text" / "frame_14.txt"
            future_img = history / "2026_07_14" / "Shift_C_img" / "future_shift_frame.jpeg"
            future_text = history / "2026_07_14" / "Shift_C_text" / "future_shift_frame.txt"
            for path in (old_img, old_text, next_img, next_text, future_img, future_text):
                _touch(path)

            summary = cleanup_shift_sources(
                history,
                "13-07-2026",
                "Shift_C",
                image_paths=[old_img, next_img],
            )

            self.assertFalse(old_img.exists())
            self.assertFalse(old_text.exists())
            self.assertFalse(next_img.exists())
            self.assertFalse(next_text.exists())
            self.assertFalse((history / "2026_07_13").exists())
            self.assertTrue(future_img.exists())
            self.assertTrue(future_text.exists())
            self.assertIn(str(history / "2026_07_13"), summary["removed_empty_date_dirs"])
            self.assertIn(str(history / "2026_07_14"), summary["kept_date_dirs"])
            self.assertEqual(summary["failed_files"], {})
            self.assertEqual(summary["failed_dirs"], {})

    def test_a_and_b_shifts_only_target_the_requested_date(self):
        with TemporaryDirectory() as tmp:
            history = Path(tmp) / "history"

            self.assertEqual(
                shift_source_dirs(history, "13-07-2026", "Shift_A"),
                [
                    history / "2026_07_13" / "Shift_A_img",
                    history / "2026_07_13" / "Shift_A_text",
                ],
            )

    def test_missing_shift_dirs_are_reported_without_failure(self):
        with TemporaryDirectory() as tmp:
            history = Path(tmp) / "history"

            summary = cleanup_shift_sources(history, "13-07-2026", "B")

            self.assertEqual(len(summary["missing_dirs"]), 2)
            self.assertEqual(summary["deleted_dirs"], [])
            self.assertEqual(summary["failed_dirs"], {})