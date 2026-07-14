from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from cli import report_workflow
from cli.report_workflow import ShiftRun, ShiftWorkflow


def _cfg():
    return {
        "history": {
            "image_root": "legacy/history",
            "shifts": [
                {"name": "Shift_A", "start": "06:00", "end": "14:00"},
                {"name": "Shift_B", "start": "14:00", "end": "22:00"},
                {"name": "Shift_C", "start": "22:00", "end": "06:00"},
            ],
        },
        "video": {"output_dir": "outputs/videos"},
        "casters": {
            "defaults": {
                "enabled": True,
                "var_root": "var",
                "database_file": "pipes.db",
                "history_dir": "history",
                "outputs": {"video_dir_template": "outputs/{caster_id}/videos"},
            },
            "items": [{"id": "caster1", "number": 1, "var_dir": "var/caster1"}],
        },
    }


def _immediate_retry(fn, **_kwargs):
    return fn()


class WorkflowSourceCleanupTest(TestCase):
    def _workflow(self, tmp: str) -> ShiftWorkflow:
        wf = ShiftWorkflow(cfg=_cfg(), selected_ids=["caster1"])
        wf.state_dir = Path(tmp)
        return wf

    def test_source_cleanup_runs_after_successful_normal_shift_video(self):
        calls = []

        class FakeVideoGenerator:
            def __init__(self, date_str, shift, cfg=None, caster=None):
                self.image_root = Path("history-root")
                self.source_image_paths = [Path("history-root/2026_07_13/Shift_C_img/frame.jpeg")]

            def generate(self):
                return "caster1.mp4"

        def fake_cleanup(history_root, date_str, shift, *, image_paths=None):
            calls.append((history_root, date_str, shift, image_paths))
            return {"deleted_files": ["history-root/2026_07_13/Shift_C_img/frame.jpeg"]}

        with (
            TemporaryDirectory() as tmp,
            patch.object(report_workflow, "ShiftVideoGenerator", FakeVideoGenerator),
            patch.object(report_workflow, "cleanup_shift_sources", fake_cleanup),
            patch.object(report_workflow, "backoff_retry", _immediate_retry),
        ):
            wf = self._workflow(tmp)
            run = ShiftRun("13-07-2026", "Shift_C")
            wf.phase_normal_shift_videos(wf.casters, run)

            result = wf.results["caster1"]

        self.assertEqual(
            calls,
            [(
                Path("history-root"),
                "13-07-2026",
                "Shift_C",
                [Path("history-root/2026_07_13/Shift_C_img/frame.jpeg")],
            )],
        )
        self.assertEqual(
            result.state["normal_shift_source_cleanup"],
            {"deleted_files": ["history-root/2026_07_13/Shift_C_img/frame.jpeg"]},
        )

    def test_source_cleanup_does_not_run_when_normal_shift_video_fails(self):
        calls = []

        class FailingVideoGenerator:
            def __init__(self, date_str, shift, cfg=None, caster=None):
                self.image_root = Path("history-root")
                self.source_image_paths = [Path("history-root/2026_07_13/Shift_C_img/frame.jpeg")]

            def generate(self):
                raise RuntimeError("video failed")

        def fake_cleanup(history_root, date_str, shift, *, image_paths=None):
            calls.append((history_root, date_str, shift, image_paths))
            return {}

        with (
            TemporaryDirectory() as tmp,
            patch.object(report_workflow, "ShiftVideoGenerator", FailingVideoGenerator),
            patch.object(report_workflow, "cleanup_shift_sources", fake_cleanup),
            patch.object(report_workflow, "backoff_retry", _immediate_retry),
        ):
            wf = self._workflow(tmp)
            wf.phase_normal_shift_videos(wf.casters, ShiftRun("13-07-2026", "Shift_C"))

            result = wf.results["caster1"]

        self.assertEqual(calls, [])
        self.assertTrue(result.errors)
        self.assertNotIn("normal_shift_source_cleanup", result.state)