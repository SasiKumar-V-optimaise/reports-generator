from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from cli import report_workflow
from cli.report_workflow import ShiftRun, ShiftWorkflow, setup_logging
from reports.common.caster_config import resolve_enabled_casters


def _cfg(tmp: Path | None = None) -> dict:
    state_dir = str(tmp / "state") if tmp else "outputs/state"
    return {
        "outputs": {
            "base_dir": "outputs",
            "logs_dir": str(tmp / "logs") if tmp else "outputs/logs",
            "state_dir": state_dir,
        },
        "history": {
            "shifts": [
                {"name": "Shift_A", "start": "06:00", "end": "14:00"},
                {"name": "Shift_B", "start": "14:00", "end": "22:00"},
                {"name": "Shift_C", "start": "22:00", "end": "06:00"},
            ],
        },
        "casters": {
            "defaults": {
                "enabled": True,
                "var_root": "../producer/var",
                "database_file": "caster_{number}_pipes.db",
                "history_dir": "history",
                "outputs": {
                    "raw_csv_dir_template": "outputs/{caster_id}/raw-csv",
                    "verified_csv_dir_template": "outputs/{caster_id}/verified-csv",
                    "diagnosis_dir_template": "outputs/{caster_id}/verified-csv",
                    "video_dir_template": "outputs/{caster_id}/videos",
                    "overlay_video_dir_template": "outputs/{caster_id}/overlay-videos",
                },
            },
            "items": [{"id": "caster4", "number": 4, "enabled": True}],
        },
    }


class ArchitectureOutputPathTest(TestCase):
    def test_new_caster_output_path_contract_resolves(self):
        caster = resolve_enabled_casters(_cfg(), ["caster4"])[0]

        self.assertEqual(caster.cfg["outputs"]["raw_csv_dir"], "outputs/caster4/raw-csv")
        self.assertEqual(caster.cfg["outputs"]["verified_csv_dir"], "outputs/caster4/verified-csv")
        self.assertEqual(caster.cfg["outputs"]["diagnosis_dir"], "outputs/caster4/verified-csv")
        self.assertEqual(caster.cfg["video"]["output_dir"], "outputs/caster4/videos")
        self.assertEqual(caster.cfg["video"]["overlay_output_dir"], "outputs/caster4/overlay-videos")

    def test_workflow_uses_configured_state_dir_and_no_nested_package_exists(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf = ShiftWorkflow(cfg=_cfg(root), selected_ids=["caster4"])

            self.assertEqual(wf.state_dir, root / "state")
            self.assertFalse((Path.cwd() / "src" / "reports_generator").exists())

    def test_setup_logging_creates_app_and_error_logs(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"

            setup_logging({"outputs": {"logs_dir": str(logs_dir)}, "logging": {"level": "INFO"}})

            self.assertTrue((logs_dir / "app.log").exists())
            self.assertTrue((logs_dir / "error.log").exists())
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)
                handler.close()

    def test_raw_csv_is_deleted_only_after_successful_upload(self):
        class SuccessfulUploader:
            def __init__(self, cfg=None, caster=None):
                pass

            def upload_csv(self, path):
                return "https://drive/success"

        class FailingUploader:
            def __init__(self, cfg=None, caster=None):
                pass

            def upload_csv(self, path):
                raise RuntimeError("upload failed")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = ShiftRun("02-07-2026", "Shift_A")

            successful_csv = root / "success.csv"
            successful_csv.write_text("raw", encoding="utf-8")
            wf = ShiftWorkflow(cfg=_cfg(root), selected_ids=["caster4"])
            wf.state_dir = root / "state-success"
            wf.state_dir.mkdir()
            caster = wf.casters[0]
            wf.results[caster.id] = report_workflow.CasterRunResult(caster=caster, csv_path=str(successful_csv))

            with patch.object(report_workflow, "GDriveUploader", SuccessfulUploader):
                wf.phase_csv_uploads([caster], run)

            self.assertFalse(successful_csv.exists())
            self.assertTrue(wf.results[caster.id].state["csv_deleted_after_upload"])

            failing_csv = root / "failure.csv"
            failing_csv.write_text("raw", encoding="utf-8")
            wf = ShiftWorkflow(cfg=_cfg(root), selected_ids=["caster4"])
            wf.state_dir = root / "state-failure"
            wf.state_dir.mkdir()
            caster = wf.casters[0]
            wf.results[caster.id] = report_workflow.CasterRunResult(caster=caster, csv_path=str(failing_csv))

            with patch.object(report_workflow, "GDriveUploader", FailingUploader):
                wf.phase_csv_uploads([caster], run)

            self.assertTrue(failing_csv.exists())
            self.assertNotIn("csv_deleted_after_upload", wf.results[caster.id].state)


    def test_verified_only_custom_window_passes_start_stop_to_exporters(self):
        calls = {}
        tmp_root = None

        class FakePipeExporter:
            def __init__(self, cfg=None, caster=None):
                self.caster = caster

            def export(self, date_str, shift, **kwargs):
                calls["raw"] = (date_str, shift, kwargs)
                path = tmp_root / "raw.csv"
                path.write_text("raw", encoding="utf-8")
                return path, 3

        class FakeVerifiedExporter:
            def __init__(self, cfg=None, caster=None):
                self.caster = caster

            def export(self, date_str, shift, csv_path, mode=None, **kwargs):
                calls["verified"] = (date_str, shift, Path(csv_path).name, mode, kwargs)
                path = tmp_root / "verified.csv"
                path.write_text("verified", encoding="utf-8")
                return path, {"verified_count": 3, "removed_count": 0, "loadcell_missing_records": []}

        with (
            TemporaryDirectory() as tmp,
            patch.object(report_workflow, "PipeExporter", FakePipeExporter),
            patch.object(report_workflow, "VerifiedPipeExporter", FakeVerifiedExporter),
        ):
            tmp_root = Path(tmp)
            wf = ShiftWorkflow(cfg=_cfg(tmp_root), selected_ids=["caster4"])
            run = ShiftRun("13-07-2026", "custom_0100_1300", "01:00", "13:00")
            wf.phase_raw_and_verified(wf.casters, run, require_raw_email_for_verified=False)

        self.assertEqual(calls["raw"], (
            "13-07-2026",
            "custom_0100_1300",
            {"start_time": "01:00", "stop_time": "13:00"},
        ))
        self.assertEqual(calls["verified"], (
            "13-07-2026",
            "custom_0100_1300",
            "raw.csv",
            "loadcell",
            {"start_time": "01:00", "stop_time": "13:00"},
        ))
        state = wf.results["caster4"].state
        self.assertEqual(state["window_mode"], "custom")
        self.assertEqual(state["start_time"], "01:00")
        self.assertEqual(state["stop_time"], "13:00")
