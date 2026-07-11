from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from reports.video.delete_old_videos import cleanup_old_videos, video_date


def _touch(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")


def _cfg(root: Path):
    return {
        "video_retention": {"keep_days": 5, "include_overlay_videos": True},
        "casters": {
            "defaults": {
                "enabled": False,
                "outputs": {
                    "video_dir_template": str(root / "{caster_id}" / "videos"),
                    "overlay_video_dir_template": str(root / "{caster_id}" / "videos-overlay"),
                },
            },
            "items": [
                {"id": "caster1", "number": 1, "enabled": True},
                {"id": "caster2", "number": 2, "enabled": False},
            ],
        },
    }


class DeleteOldVideosTest(TestCase):
    def test_video_date_supports_report_and_missing_loadcell_names(self):
        self.assertEqual(video_date(Path("08-07-2026_caster2_shift_b.mp4")), date(2026, 7, 8))
        self.assertEqual(video_date(Path("missing_loadcell_caster2_08072026_shift_b_overlay.mp4")), date(2026, 7, 8))
        self.assertIsNone(video_date(Path("video_without_date.mp4")))
        self.assertIsNone(video_date(Path("99-99-9999_caster2_shift_b.mp4")))

    def test_cleanup_keeps_last_configured_days_for_each_caster(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_caster1 = root / "caster1" / "videos" / "06-07-2026_caster1_shift_a.mp4"
            cutoff_day = root / "caster1" / "videos" / "07-07-2026_caster1_shift_a.mp4"
            current_day = root / "caster1" / "videos" / "11-07-2026_caster1_shift_a.mp4"
            unknown = root / "caster1" / "videos" / "caster1_latest.mp4"
            old_overlay = root / "caster1" / "videos-overlay" / "missing_loadcell_caster1_06072026_shift_a_overlay.mp4"
            old_caster2 = root / "caster2" / "videos" / "06-07-2026_caster2_shift_a.mp4"

            for path in [old_caster1, cutoff_day, current_day, unknown, old_overlay, old_caster2]:
                _touch(path)

            summary = cleanup_old_videos(_cfg(root), today=date(2026, 7, 11))

            self.assertFalse(old_caster1.exists())
            self.assertFalse(old_overlay.exists())
            self.assertFalse(old_caster2.exists())
            self.assertTrue(cutoff_day.exists())
            self.assertTrue(current_day.exists())
            self.assertTrue(unknown.exists())
            self.assertEqual(summary["scanned"], 6)
            self.assertEqual(summary["deleted"], 3)
            self.assertEqual(summary["kept"], 2)
            self.assertEqual(summary["skipped"], 1)

    def test_dry_run_reports_deletions_without_removing_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_video = root / "caster1" / "videos" / "06-07-2026_caster1_shift_a.mp4"
            _touch(old_video)

            summary = cleanup_old_videos(_cfg(root), today=date(2026, 7, 11), dry_run=True)

            self.assertTrue(old_video.exists())
            self.assertEqual(summary["deleted"], 0)
            self.assertEqual(summary["would_delete"], 1)