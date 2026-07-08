import argparse
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reports.common.caster_config import CasterConfig, caster_label, resolve_enabled_casters
from reports.common.config_loader import load_runtime_config
from reports.common.email_sender import EmailSender
from reports.common.gdrive_uploader import GDriveUploader
from reports.pipes.pipe_exporter import PipeExporter
from reports.pipes.verified_pipes import VerifiedPipeExporter
from reports.video.video_generator import ShiftVideoGenerator
from reports.video.video_overlay import ShiftVideoOverlayGenerator


logger = logging.getLogger("reports-generator")


@dataclass(frozen=True)
class ShiftRun:
    date_str: str
    shift_name: str


@dataclass
class CasterRunResult:
    caster: CasterConfig
    state: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    csv_path: str | None = None
    csv_drive_link: str | None = None
    pipe_count: int | str = 0
    raw_email_sent: bool = False
    verified_path: str | None = None
    verified_summary: dict | None = None
    diagnosis_path: str | None = None
    diagnosis_summary: dict | None = None
    missing_overlay_link: str | None = None
    missing_normal_link: str | None = None
    full_shift_video_path: str | None = None


def setup_logging(cfg: dict):
    level_name = (cfg.get("logging", {}) or {}).get("level", "INFO")
    level = getattr(logging, str(level_name).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _now():
    return datetime.now()


def detect_shift_for_trigger(now: datetime) -> ShiftRun | None:
    def in_window(target_h: int, target_m: int, minutes_slack: int = 5) -> bool:
        target = target_h * 60 + target_m
        current = now.hour * 60 + now.minute
        return target <= current <= (target + minutes_slack)

    if in_window(6, 0):
        return ShiftRun((now - timedelta(days=1)).strftime("%d-%m-%Y"), "Shift_C")
    if in_window(14, 0):
        return ShiftRun(now.strftime("%d-%m-%Y"), "Shift_A")
    if in_window(22, 0):
        return ShiftRun(now.strftime("%d-%m-%Y"), "Shift_B")
    return None


def backoff_retry(fn, *, tries=4, base_delay=2.0, what="operation"):
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as exc:
            last_err = exc
            if attempt == tries:
                break
            sleep_s = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "%s failed (attempt %s/%s). Retrying in %.1fs. Error=%s",
                what,
                attempt,
                tries,
                sleep_s,
                exc,
            )
            time.sleep(sleep_s)
    raise RuntimeError(f"{what} failed after {tries} tries: {last_err}") from last_err


class ShiftWorkflow:
    def __init__(self, cfg: dict | None = None, selected_ids: list[str] | None = None):
        self.root = PROJECT_ROOT
        self.cfg = cfg or load_runtime_config()
        self.multi_caster_mode = isinstance(self.cfg.get("casters"), dict)
        self.casters = resolve_enabled_casters(self.cfg, selected_ids)
        self.state_dir = self.root / "outputs" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._mailers: dict[str, EmailSender] = {}
        self.results: dict[str, CasterRunResult] = {}

    def _run_key(self, run: ShiftRun) -> str:
        return f"{run.date_str.replace('-', '')}_{run.shift_name.lower()}"

    def _state_path(self, run: ShiftRun, caster: CasterConfig | None = None) -> Path:
        key = self._run_key(run)
        if caster and caster.file_token:
            return self.state_dir / f"{caster.file_token}_{key}.json"
        return self.state_dir / f"{key}.json"

    def _multi_state_path(self, run: ShiftRun) -> Path:
        return self.state_dir / f"multi_{self._run_key(run)}.json"

    def _load_state(self, run: ShiftRun, caster: CasterConfig) -> dict:
        path = self._state_path(run, caster)
        if path.exists():
            return json.loads(path.read_text())
        return {}

    def _save_state(self, run: ShiftRun, caster: CasterConfig, state: dict):
        self._state_path(run, caster).write_text(json.dumps(state, indent=2, sort_keys=True))

    def _save_multi_state(self, run: ShiftRun, data: dict):
        self._multi_state_path(run).write_text(json.dumps(data, indent=2, sort_keys=True))

    @staticmethod
    def _clear_previous_run_outputs(state: dict):
        prefixes = (
            "csv_",
            "verified_pipes_",
            "diagnosis_",
            "missing_loadcell_",
            "normal_shift_video_",
            "final_summary_email_",
            "video_",
        )
        exact_keys = {
            "pipe_count",
            "emailed_csv",
            "emailed_verified_pipes",
            "verified_pipe_records_recipients",
            "diagnosis_recipients",
            "errors",
        }
        for key in list(state):
            if key in exact_keys or any(key.startswith(prefix) for prefix in prefixes):
                state.pop(key, None)

    def _mailer(self, caster: CasterConfig) -> EmailSender:
        if caster.id not in self._mailers:
            self._mailers[caster.id] = EmailSender(cfg=caster.cfg)
        return self._mailers[caster.id]

    @staticmethod
    def _normalize_recipients(recipients) -> list[str]:
        if recipients is None:
            return []
        if isinstance(recipients, str):
            recipients = [recipients]
        return [str(item).strip() for item in recipients if str(item).strip()]

    def _diagnosis_recipients(self, cfg: dict) -> list[str]:
        return self._normalize_recipients((cfg.get("email", {}) or {}).get("diagnosis_recipients"))

    def _verified_pipe_records_recipients(self, cfg: dict) -> list[str]:
        return self._normalize_recipients(cfg.get("verified_pipe_records_recipients"))

    @staticmethod
    def _verified_pipes_mode(cfg: dict) -> str:
        return str(cfg.get("verified_pipes_mode") or cfg.get("verfied_pipes_mode") or "loadcell").strip().lower()

    @staticmethod
    def _email_password_skip_reason(cfg: dict) -> str | None:
        email_cfg = cfg.get("email", {}) or {}
        password_env = email_cfg.get("password_env")
        if password_env:
            return None if os.getenv(password_env) else f"Email password environment variable {password_env} is not set"
        return None if email_cfg.get("password") else "No email.password or email.password_env configured"

    @staticmethod
    def _parse_positive_int(value, *, default: int, name: str) -> int:
        if value is None:
            return default
        seconds = int(value)
        if seconds <= 0:
            raise ValueError(f"{name} must be greater than 0")
        return seconds

    @staticmethod
    def _format_seconds_hms(seconds) -> str:
        if seconds is None:
            return "N/A"
        total_seconds = abs(int(round(float(seconds))))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _diagnosis_gap_labels(self, diagnosis_summary: dict | None) -> tuple[str, str]:
        summary = diagnosis_summary or {}
        min_label = summary.get("t_origin_gap_min_label")
        if not min_label and summary.get("t_origin_gap_min_seconds") is not None:
            min_label = self._format_seconds_hms(summary.get("t_origin_gap_min_seconds"))
        max_label = summary.get("t_origin_gap_max_label")
        if not max_label and summary.get("t_origin_gap_max_seconds") is not None:
            max_label = self._format_seconds_hms(summary.get("t_origin_gap_max_seconds"))
        return str(min_label or "00:01:50"), str(max_label or "00:03:10")

    def _removed_pipe_reason(self, verified_summary: dict | None) -> str:
        if not verified_summary:
            return "N/A"
        try:
            removed_count = int(verified_summary.get("removed_count", 0))
        except (TypeError, ValueError):
            removed_count = 0
        if removed_count <= 0:
            return "N/A"
        window_seconds = verified_summary.get("gate_open_max_interval_seconds")
        window_text = self._format_seconds_hms(window_seconds) if window_seconds is not None else "configured window"
        return f"Pipe checkpoint was not 1 and G2 was not open within {window_text} from T-Origin"

    def _missing_loadcell_video_cfg(self, cfg: dict) -> dict:
        video_cfg = cfg.get("missing_loadcell_video", {}) or {}
        return {
            "enabled": bool(video_cfg.get("enabled", True)),
            "pre_origin_seconds": self._parse_positive_int(
                video_cfg.get("pre_origin_seconds"),
                default=60,
                name="missing_loadcell_video.pre_origin_seconds",
            ),
            "clip_duration_seconds": self._parse_positive_int(
                video_cfg.get("clip_duration_seconds"),
                default=300,
                name="missing_loadcell_video.clip_duration_seconds",
            ),
            "delete_after_upload": bool(video_cfg.get("delete_after_upload", True)),
        }

    @staticmethod
    def _normalize_shift_name(shift: str) -> str:
        value = str(shift).strip()
        if value.lower().startswith("shift_"):
            letter = value.split("_", 1)[1].upper()
        else:
            letter = value.upper()
        if letter not in {"A", "B", "C"}:
            raise ValueError("Invalid shift. Use A, B, or C")
        return f"Shift_{letter}"

    def _shift_window(self, cfg: dict, run: ShiftRun) -> tuple[datetime, datetime]:
        shifts_cfg = (cfg.get("history", {}) or {}).get("shifts", [])
        shifts = {str(item["name"]).lower(): (item["start"], item["end"]) for item in shifts_cfg}
        shift_key = run.shift_name.lower()
        if shift_key not in shifts:
            raise ValueError(f"Invalid shift: {run.shift_name}")
        start_s, end_s = shifts[shift_key]
        start = datetime.strptime(f"{run.date_str} {start_s}", "%d-%m-%Y %H:%M")
        end = datetime.strptime(f"{run.date_str} {end_s}", "%d-%m-%Y %H:%M")
        if end <= start:
            end += timedelta(days=1)
        return start, end

    @staticmethod
    def _parse_origin_time(value: str | None) -> datetime | None:
        if not value:
            return None
        text = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _merge_overlay_labels(existing: str, new: str) -> str:
        parts = [part.strip() for part in f"{existing}, {new}".split(",") if part.strip()]
        return ", ".join(dict.fromkeys(parts))

    def _build_missing_loadcell_windows(
        self,
        cfg: dict,
        run: ShiftRun,
        records: list[dict],
    ) -> tuple[list[dict], int]:
        video_cfg = self._missing_loadcell_video_cfg(cfg)
        shift_start, shift_end = self._shift_window(cfg, run)
        pre_origin = timedelta(seconds=video_cfg["pre_origin_seconds"])
        duration = timedelta(seconds=video_cfg["clip_duration_seconds"])
        windows = []
        skipped = 0
        for idx, record in enumerate(records, start=1):
            origin = self._parse_origin_time(record.get("origin_time") or record.get("origin_time_raw"))
            if origin is None:
                skipped += 1
                continue
            raw_start = origin - pre_origin
            raw_end = raw_start + duration
            start = max(raw_start, shift_start)
            end = min(raw_end, shift_end)
            if end <= start:
                skipped += 1
                continue
            pipe_uid = str(record.get("pipe_uid") or "").strip()
            label = f"{pipe_uid} @ {origin:%H:%M:%S}" if pipe_uid else f"Pipe {idx} @ {origin:%H:%M:%S}"
            windows.append({"start": start, "end": end, "label": label})

        windows = sorted(windows, key=lambda item: item["start"])
        if not windows:
            return [], skipped
        merged = [windows[0].copy()]
        for window in windows[1:]:
            current = merged[-1]
            if window["start"] <= current["end"]:
                current["end"] = max(current["end"], window["end"])
                current["label"] = self._merge_overlay_labels(current["label"], window["label"])
            else:
                merged.append(window.copy())
        return merged, skipped

    @staticmethod
    def _serialize_windows(windows: list[dict]) -> list[dict]:
        return [
            {
                "start": window["start"].isoformat(timespec="seconds"),
                "end": window["end"].isoformat(timespec="seconds"),
                "label": window["label"],
            }
            for window in windows
        ]

    def _record_error(self, run: ShiftRun, result: CasterRunResult, label: str, exc_text: str | None = None):
        message = f"{label}:\n{exc_text or traceback.format_exc()}"
        result.errors.append(message)
        result.state["errors"] = result.errors
        self._save_state(run, result.caster, result.state)

    def _skip_missing_loadcell_videos(self, run: ShiftRun, result: CasterRunResult, reason: str):
        for kind in ("overlay", "normal"):
            result.state[f"missing_loadcell_{kind}_video_skipped"] = True
            result.state[f"missing_loadcell_{kind}_video_skip_reason"] = reason
        self._save_state(run, result.caster, result.state)

    def _generate_missing_loadcell_videos(self, run: ShiftRun, result: CasterRunResult):
        cfg = result.caster.cfg
        video_cfg = self._missing_loadcell_video_cfg(cfg)
        records = (result.verified_summary or {}).get("loadcell_missing_records", []) or []
        result.state["missing_loadcell_video_strategy"] = "merged_window_compilation_overlay_and_normal"
        result.state["missing_loadcell_video_record_count"] = len(records)

        if not video_cfg["enabled"]:
            self._skip_missing_loadcell_videos(run, result, "missing_loadcell_video.enabled is false")
            return
        if not result.verified_summary:
            self._skip_missing_loadcell_videos(run, result, "Verified pipe summary unavailable")
            return
        if not records:
            self._skip_missing_loadcell_videos(run, result, "No loadcell-missing pipes")
            return

        windows, skipped = self._build_missing_loadcell_windows(cfg, run, records)
        result.state["missing_loadcell_overlay_window_count"] = len(windows)
        result.state["missing_loadcell_overlay_skipped_record_count"] = skipped
        result.state["missing_loadcell_overlay_windows"] = self._serialize_windows(windows)
        self._save_state(run, result.caster, result.state)
        if not windows:
            self._skip_missing_loadcell_videos(run, result, "No valid loadcell-missing video windows")
            return

        shift_key = run.shift_name.lower()
        caster_part = result.caster.file_token or "legacy"
        output_name = f"missing_loadcell_{caster_part}_{run.date_str.replace('-', '')}_{shift_key}_overlay.mp4"
        normal_output_name = f"missing_loadcell_{caster_part}_{run.date_str.replace('-', '')}_{shift_key}_normal.mp4"
        overlay_gen = ShiftVideoOverlayGenerator(
            run.date_str,
            run.shift_name.split("_")[1],
            windows=windows,
            output_name=output_name,
            normal_output_name=normal_output_name,
            cfg=cfg,
            caster=result.caster,
        )
        overlay_path = backoff_retry(lambda: overlay_gen.generate(), what=f"{result.caster.id} missing-loadcell video")
        normal_path = str(overlay_gen.normal_output_path)
        result.state["missing_loadcell_overlay_video_path"] = overlay_path
        result.state["missing_loadcell_normal_video_path"] = normal_path
        self._save_state(run, result.caster, result.state)

        uploader = GDriveUploader(cfg=cfg, caster=result.caster)
        overlay_link = backoff_retry(lambda: uploader.upload_video(overlay_path), what=f"{result.caster.id} overlay upload")
        normal_link = backoff_retry(lambda: uploader.upload_video(normal_path), what=f"{result.caster.id} normal upload")
        result.missing_overlay_link = overlay_link
        result.missing_normal_link = normal_link
        result.state["missing_loadcell_overlay_video_drive_link"] = overlay_link
        result.state["missing_loadcell_normal_video_drive_link"] = normal_link
        result.state["missing_loadcell_video_uploaded_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(run, result.caster, result.state)

        if video_cfg["delete_after_upload"]:
            for kind, path in (("overlay", overlay_path), ("normal", normal_path)):
                try:
                    Path(path).unlink(missing_ok=True)
                    result.state[f"missing_loadcell_{kind}_video_deleted_after_upload"] = True
                except Exception as exc:
                    result.state[f"missing_loadcell_{kind}_video_deleted_after_upload"] = False
                    logger.warning("Failed to delete %s missing-loadcell video | %s | error=%s", kind, path, exc)
            self._save_state(run, result.caster, result.state)

    def _send_raw_csv_email(self, run: ShiftRun, result: CasterRunResult) -> bool:
        cfg = result.caster.cfg
        if not bool((cfg.get("email", {}) or {}).get("send_csv_attachment", True)):
            result.state["emailed_csv"] = False
            result.state["csv_email_skip_reason"] = "email.send_csv_attachment is false"
            self._save_state(run, result.caster, result.state)
            return False
        password_skip_reason = self._email_password_skip_reason(cfg)
        if password_skip_reason:
            result.state["emailed_csv"] = False
            result.state["csv_email_skip_reason"] = password_skip_reason
            self._save_state(run, result.caster, result.state)
            return False

        subject = f"Pipe Report CSV - {caster_label(result.caster, cfg)} - {run.shift_name} - {run.date_str}"
        body = "\n".join([
            "Pipe Production Report",
            "",
            f"Date       : {run.date_str}",
            f"Caster id  : {result.caster.id}",
            f"Caster     : {caster_label(result.caster, cfg)}",
            f"Shift      : {run.shift_name}",
            f"Pipe Count : {result.pipe_count}",
            "",
            "CSV attached.",
        ])
        backoff_retry(lambda: self._mailer(result.caster).send_csv(subject, body, result.csv_path), what="Email CSV")
        result.state["emailed_csv"] = True
        result.raw_email_sent = True
        self._save_state(run, result.caster, result.state)
        return True

    def _send_verified_pipes_report(self, run: ShiftRun, result: CasterRunResult):
        cfg = result.caster.cfg
        verified_exporter = VerifiedPipeExporter(cfg=cfg, caster=result.caster)
        verified_path_obj, verified_summary = backoff_retry(
            lambda: verified_exporter.export(
                run.date_str,
                run.shift_name,
                result.csv_path,
                mode=self._verified_pipes_mode(cfg),
            ),
            what=f"{result.caster.id} verified pipes CSV export",
        )
        result.verified_path = str(verified_path_obj)
        result.verified_summary = verified_summary
        result.state["verified_pipes_csv_path"] = result.verified_path
        result.state["verified_pipes_summary"] = verified_summary
        self._save_state(run, result.caster, result.state)

        recipients = self._verified_pipe_records_recipients(cfg)
        if not recipients:
            result.state["emailed_verified_pipes"] = False
            result.state["verified_pipes_skip_reason"] = "No verified_pipe_records_recipients configured"
            self._save_state(run, result.caster, result.state)
            return
        password_skip_reason = self._email_password_skip_reason(cfg)
        if password_skip_reason:
            result.state["emailed_verified_pipes"] = False
            result.state["verified_pipes_skip_reason"] = password_skip_reason
            self._save_state(run, result.caster, result.state)
            return

        subject = (
            f"Verified Pipe Records - {caster_label(result.caster, cfg)} - "
            f"{run.shift_name} - {run.date_str} - Pipe Count {verified_summary['verified_count']}"
        )
        body = "\n".join([
            f"Date                  : {run.date_str}",
            f"Caster id             : {result.caster.id}",
            f"Caster                : {caster_label(result.caster, cfg)}",
            f"Shift                 : {run.shift_name}",
            "",
            f"Pipe Count            : {verified_summary['verified_count']}",
            f"Removed Pipe Count    : {verified_summary.get('removed_count', 'N/A')}",
        ])
        backoff_retry(
            lambda: self._mailer(result.caster).send_csv(
                subject,
                body,
                result.verified_path,
                recipients=recipients,
            ),
            what=f"{result.caster.id} verified pipes email",
        )
        result.state["emailed_verified_pipes"] = True
        result.state["verified_pipe_records_recipients"] = recipients
        self._save_state(run, result.caster, result.state)

    def _send_diagnosis_report(self, run: ShiftRun, result: CasterRunResult):
        cfg = result.caster.cfg
        diagnosis_exporter = PipeExporter(cfg=cfg, caster=result.caster)
        diagnosis_path_obj, diagnosis_summary = backoff_retry(
            lambda: diagnosis_exporter.export_diagnosis(run.date_str, run.shift_name),
            what=f"{result.caster.id} diagnosis XLSX export",
        )
        result.diagnosis_path = str(diagnosis_path_obj)
        result.diagnosis_summary = diagnosis_summary
        result.state["diagnosis_xlsx_path"] = result.diagnosis_path
        result.state["diagnosis_summary"] = diagnosis_summary
        self._save_state(run, result.caster, result.state)

        recipients = self._diagnosis_recipients(cfg)
        if not recipients:
            result.state["emailed_diagnosis_xlsx"] = False
            result.state["diagnosis_skip_reason"] = "No email.diagnosis_recipients configured"
            self._save_state(run, result.caster, result.state)
            return
        password_skip_reason = self._email_password_skip_reason(cfg)
        if password_skip_reason:
            result.state["emailed_diagnosis_xlsx"] = False
            result.state["diagnosis_skip_reason"] = password_skip_reason
            self._save_state(run, result.caster, result.state)
            return

        min_gap_label, max_gap_label = self._diagnosis_gap_labels(diagnosis_summary)
        subject = f"Pipe Diagnosis Report - {caster_label(result.caster, cfg)} - {run.shift_name} - {run.date_str}"
        body = "\n".join([
            "Pipe Diagnosis Report",
            "",
            f"Date                       : {run.date_str}",
            f"Caster id                  : {result.caster.id}",
            f"Caster                     : {caster_label(result.caster, cfg)}",
            f"Shift                      : {run.shift_name}",
            f"Pipe Count                 : {diagnosis_summary['pipe_count']}",
            f"Abnormal Rows              : {diagnosis_summary['abnormal_count']}",
            f"T-Origin Gap Abnormal      : {diagnosis_summary['t_origin_gap_abnormal_count']}",
            f"T-Origin Gap Above {max_gap_label}: {diagnosis_summary['t_origin_gap_too_slow_count']}",
            f"T-Origin Gap Below {min_gap_label}: {diagnosis_summary['t_origin_gap_too_fast_count']}",
            f"Loadcell Missing Rows      : {diagnosis_summary['loadcell_missing_count']}",
            "",
            "Diagnosis Excel file attached. Abnormal rows are highlighted red.",
        ])
        backoff_retry(
            lambda: self._mailer(result.caster).send_csv(
                subject,
                body,
                result.diagnosis_path,
                recipients=recipients,
            ),
            what=f"{result.caster.id} diagnosis email",
        )
        result.state["emailed_diagnosis_xlsx"] = True
        result.state["diagnosis_recipients"] = recipients
        self._save_state(run, result.caster, result.state)

    def load_selected_enabled_casters(self) -> list[CasterConfig]:
        return self.casters

    def phase_raw_and_verified(self, casters: list[CasterConfig], run: ShiftRun, *, require_raw_email_for_verified: bool = True):
        force = os.getenv("FORCE_RERUN") == "1"
        for caster in casters:
            result = CasterRunResult(caster=caster)
            self.results[caster.id] = result
            state = self._load_state(run, caster)
            raw_verified_done = bool(state.get("csv_path") and state.get("verified_pipes_csv_path"))
            if state.get("status") == "success" and raw_verified_done and not force:
                logger.info("Already success for %s %s %s. Skipping raw/verified.", caster.id, run.date_str, run.shift_name)
                result.state = state
                result.csv_path = state.get("csv_path")
                result.verified_path = state.get("verified_pipes_csv_path")
                result.pipe_count = state.get("pipe_count", 0)
                result.csv_drive_link = state.get("csv_drive_link")
                result.verified_summary = state.get("verified_pipes_summary")
                continue

            self._clear_previous_run_outputs(state)
            state.update({
                "date": run.date_str,
                "shift": run.shift_name,
                "caster_id": caster.id,
                "caster_number": caster.number,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "status": "raw_verified_running",
            })
            result.state = state
            self._save_state(run, caster, state)
            logger.info("Raw/verified phase start | caster=%s | date=%s | shift=%s", caster.id, run.date_str, run.shift_name)

            try:
                exporter = PipeExporter(cfg=caster.cfg, caster=caster)
                csv_path_obj, pipe_count = backoff_retry(
                    lambda: exporter.export(run.date_str, run.shift_name),
                    what=f"{caster.id} CSV export",
                )
                result.csv_path = str(csv_path_obj)
                result.pipe_count = pipe_count
                state["csv_path"] = result.csv_path
                state["pipe_count"] = pipe_count
                self._save_state(run, caster, state)
                logger.info("CSV export success | caster=%s | pipe_count=%s | path=%s", caster.id, pipe_count, result.csv_path)
            except Exception:
                self._record_error(run, result, "CSV export failed")
                logger.exception("CSV export failed | caster=%s", caster.id)

            if result.csv_path:
                try:
                    self._send_raw_csv_email(run, result)
                except Exception:
                    self._record_error(run, result, "Email CSV failed")
                    logger.exception("CSV email failed | caster=%s", caster.id)

            if result.csv_path and (result.raw_email_sent or not require_raw_email_for_verified):
                try:
                    self._send_verified_pipes_report(run, result)
                except Exception:
                    self._record_error(run, result, "Verified pipes email failed")
                    logger.exception("Verified pipes failed | caster=%s", caster.id)
            elif result.csv_path and require_raw_email_for_verified:
                state["emailed_verified_pipes"] = False
                state["verified_pipes_skip_reason"] = "Raw CSV email was not sent"
                self._save_state(run, caster, state)
            else:
                state["emailed_verified_pipes"] = False
                state["verified_pipes_skip_reason"] = "Raw CSV export failed"
                self._save_state(run, caster, state)

            state["raw_verified_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, caster, state)

    def phase_csv_uploads(self, casters: list[CasterConfig], run: ShiftRun):
        for caster in casters:
            result = self.results.setdefault(caster.id, CasterRunResult(caster=caster))
            if not result.csv_path:
                continue
            try:
                uploader = GDriveUploader(cfg=caster.cfg, caster=caster)
                result.csv_drive_link = backoff_retry(
                    lambda: uploader.upload_csv(result.csv_path),
                    what=f"{caster.id} Drive upload CSV",
                )
                result.state["csv_drive_link"] = result.csv_drive_link
                self._save_state(run, caster, result.state)
                try:
                    Path(result.csv_path).unlink(missing_ok=True)
                    result.state["csv_deleted_after_upload"] = True
                except Exception as exc:
                    result.state["csv_deleted_after_upload"] = False
                    logger.warning("Failed to delete CSV | caster=%s | path=%s | error=%s", caster.id, result.csv_path, exc)
                self._save_state(run, caster, result.state)
            except Exception:
                self._record_error(run, result, "Drive upload CSV failed")
                logger.exception("Drive upload CSV failed | caster=%s", caster.id)

    def phase_diagnosis(self, casters: list[CasterConfig], run: ShiftRun):
        for caster in casters:
            result = self.results.setdefault(caster.id, CasterRunResult(caster=caster))
            result.state.setdefault("date", run.date_str)
            result.state.setdefault("shift", run.shift_name)
            result.state.setdefault("caster_id", caster.id)
            result.state["diagnosis_started_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, caster, result.state)
            try:
                self._send_diagnosis_report(run, result)
            except Exception:
                self._record_error(run, result, "Diagnosis XLSX email failed")
                logger.exception("Diagnosis failed | caster=%s", caster.id)
            result.state["diagnosis_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, caster, result.state)

    def phase_videos(self, casters: list[CasterConfig], run: ShiftRun):
        for caster in casters:
            result = self.results.setdefault(caster.id, CasterRunResult(caster=caster))
            try:
                self._generate_missing_loadcell_videos(run, result)
            except Exception:
                self._record_error(run, result, "Missing-loadcell video generation/upload failed")
                result.state["missing_loadcell_video_error"] = traceback.format_exc()
                self._save_state(run, caster, result.state)
                logger.exception("Missing-loadcell video failed | caster=%s", caster.id)

            try:
                if (caster.cfg.get("video", {}) or {}).get("enabled", True) is False:
                    result.state["normal_shift_video_skipped"] = True
                    result.state["normal_shift_video_skip_reason"] = "video.enabled is false"
                    self._save_state(run, caster, result.state)
                    continue
                video_gen = ShiftVideoGenerator(
                    run.date_str,
                    run.shift_name.split("_")[1],
                    cfg=caster.cfg,
                    caster=caster,
                )
                result.full_shift_video_path = backoff_retry(
                    lambda: video_gen.generate(),
                    what=f"{caster.id} normal shift video generation",
                )
                result.state["normal_shift_video_path"] = result.full_shift_video_path
                result.state["normal_shift_video_uploaded"] = False
                result.state["video_path"] = result.full_shift_video_path
                result.state["video_drive_link"] = None
                self._save_state(run, caster, result.state)
            except Exception:
                self._record_error(run, result, "Normal shift video generation failed")
                result.state["normal_shift_video_error"] = traceback.format_exc()
                self._save_state(run, caster, result.state)
                logger.exception("Normal shift video failed | caster=%s", caster.id)

    def _result_summary_lines(self, result: CasterRunResult) -> list[str]:
        verified_summary = result.verified_summary or result.state.get("verified_pipes_summary") or {}
        diagnosis_summary = result.diagnosis_summary or result.state.get("diagnosis_summary") or {}
        raw_count = result.pipe_count if result.pipe_count not in (None, "") else result.state.get("pipe_count", "N/A")
        verified_count = verified_summary.get("verified_count", "N/A")
        removed_count = verified_summary.get("removed_count", "N/A")
        diagnosis_status = (
            "sent" if result.state.get("emailed_diagnosis_xlsx") else
            result.state.get("diagnosis_skip_reason") or ("failed" if result.state.get("diagnosis_error") else "N/A")
        )
        overlay_skip_reason = result.state.get("missing_loadcell_overlay_video_skip_reason")
        overlay_link = result.missing_overlay_link or result.state.get("missing_loadcell_overlay_video_drive_link")
        normal_link = result.missing_normal_link or result.state.get("missing_loadcell_normal_video_drive_link")
        video_status = result.full_shift_video_path or result.state.get("normal_shift_video_path")
        if not video_status:
            video_status = result.state.get("normal_shift_video_skip_reason") or ("failed" if result.state.get("normal_shift_video_error") else "N/A")
        return [
            f"{caster_label(result.caster, result.caster.cfg)} ({result.caster.id})",
            f"  Raw Pipe Count              : {raw_count}",
            f"  Verified Pipe Count         : {verified_count}",
            f"  Removed Pipe Count          : {removed_count}",
            f"  Removed Pipe Reason         : {self._removed_pipe_reason(verified_summary)}",
            f"  Diagnosis Status            : {diagnosis_status}",
            f"  Diagnosis Pipe Count        : {diagnosis_summary.get('pipe_count', 'N/A')}",
            f"  Raw CSV Drive Link          : {result.csv_drive_link or result.state.get('csv_drive_link') or 'N/A'}",
            f"  Missing Overlay Link        : {overlay_link or (f'N/A ({overlay_skip_reason})' if overlay_skip_reason else 'N/A')}",
            f"  Missing Normal Link         : {normal_link or 'N/A'}",
            f"  Full Shift Video            : {video_status}",
        ]

    def send_final_multi_caster_summary(self, casters: list[CasterConfig], run: ShiftRun):
        body_lines = [
            "Pipe Production Summary",
            "",
            f"Date  : {run.date_str}",
            f"Shift : {run.shift_name}",
            "",
        ]
        attachments = []
        all_errors = []
        multi_state = {
            "date": run.date_str,
            "shift": run.shift_name,
            "caster_ids": [caster.id for caster in casters],
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        for caster in casters:
            result = self.results.setdefault(caster.id, CasterRunResult(caster=caster))
            body_lines.extend(self._result_summary_lines(result))
            body_lines.append("")
            if result.diagnosis_path and Path(result.diagnosis_path).exists():
                attachments.append(result.diagnosis_path)
            if result.errors:
                all_errors.extend(f"{caster.id}: {error}" for error in result.errors)
        if all_errors:
            body_lines.extend(["Errors", "", *all_errors])

        subject = (
            f"Final Summary - All Casters - {run.shift_name} - {run.date_str}"
            if self.multi_caster_mode
            else f"Pipe Recordings - {run.shift_name} - {run.date_str}"
        )
        multi_state["errors"] = all_errors
        try:
            base_caster = casters[0]
            password_skip_reason = self._email_password_skip_reason(base_caster.cfg)
            if password_skip_reason:
                multi_state["final_summary_email_sent"] = False
                multi_state["final_summary_email_skip_reason"] = password_skip_reason
                return
            backoff_retry(
                lambda: self._mailer(base_caster).send(subject, "\n".join(body_lines), attachments=attachments),
                what="Final summary email",
            )
            multi_state["final_summary_email_sent"] = True
        except Exception:
            multi_state["final_summary_email_sent"] = False
            multi_state["final_summary_email_error"] = traceback.format_exc()
            logger.exception("Final summary email failed")
        finally:
            multi_state["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_multi_state(run, multi_state)

        for caster in casters:
            result = self.results.setdefault(caster.id, CasterRunResult(caster=caster))
            result.state["status"] = "partial_failure" if result.errors else "success"
            result.state["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, caster, result.state)

    def run_verified_only(self, run: ShiftRun):
        casters = self.load_selected_enabled_casters()
        logger.info("Verified-only workflow start | date=%s | shift=%s | casters=%s", run.date_str, run.shift_name, [c.id for c in casters])
        self.phase_raw_and_verified(casters, run, require_raw_email_for_verified=False)
        for caster in casters:
            result = self.results.setdefault(caster.id, CasterRunResult(caster=caster))
            result.state["status"] = "partial_failure" if result.errors else "success"
            result.state["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, caster, result.state)
        logger.info("Verified-only workflow finished")

    def run_diagnosis_only(self, run: ShiftRun):
        casters = self.load_selected_enabled_casters()
        logger.info("Diagnosis-only workflow start | date=%s | shift=%s | casters=%s", run.date_str, run.shift_name, [c.id for c in casters])
        self.phase_diagnosis(casters, run)
        for caster in casters:
            result = self.results.setdefault(caster.id, CasterRunResult(caster=caster))
            result.state["status"] = "partial_failure" if result.errors else "success"
            result.state["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, caster, result.state)
        logger.info("Diagnosis-only workflow finished")

    def run(self, run: ShiftRun):
        casters = self.load_selected_enabled_casters()
        logger.info("Workflow start | date=%s | shift=%s | casters=%s", run.date_str, run.shift_name, [c.id for c in casters])
        self.phase_raw_and_verified(casters, run)
        self.phase_csv_uploads(casters, run)
        self.phase_diagnosis(casters, run)
        self.phase_videos(casters, run)
        self.send_final_multi_caster_summary(casters, run)
        logger.info("Workflow finished | date=%s | shift=%s", run.date_str, run.shift_name)

    def validate_config(self) -> str:
        lines = []
        for caster in self.casters:
            cfg = caster.cfg
            root = self.root
            db_path = (root / cfg.get("database", {}).get("path", "")).resolve()
            history_root = (root / cfg.get("history", {}).get("image_root", "")).resolve()
            rois_path = (root / cfg.get("rois", {}).get("path", "")).resolve()
            lines.extend([
                f"{caster.id}:",
                f"  enabled: {caster.enabled}",
                f"  caster_number: {caster.number}",
                f"  database.path: {db_path} (exists={db_path.exists()})",
                f"  history.image_root: {history_root} (exists={history_root.exists()})",
                f"  rois.path: {rois_path} (exists={rois_path.exists()})",
                f"  outputs.csv_dir: {cfg.get('outputs', {}).get('csv_dir')}",
                f"  video.output_dir: {cfg.get('video', {}).get('output_dir')}",
                f"  video.overlay_output_dir: {cfg.get('video', {}).get('overlay_output_dir')}",
                f"  gdrive.pipes_csv_dir: {cfg.get('gdrive', {}).get('pipes_csv_dir')}",
                f"  gdrive.videos_dir: {cfg.get('gdrive', {}).get('videos_dir')}",
            ])
        return "\n".join(lines)


def _selected_ids_from_args(args) -> list[str] | None:
    selected = []
    if args.caster:
        selected.append(args.caster)
    if args.casters:
        selected.extend(part.strip() for part in args.casters.split(",") if part.strip())
    if args.all_casters:
        return None
    return selected or None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--shift")
    parser.add_argument("--diagnosis-only", action="store_true")
    parser.add_argument("--verified-only", action="store_true", help="Run raw pipe CSV and verified pipes only")
    parser.add_argument("--caster", help="Single caster id, for example caster1")
    parser.add_argument("--casters", help="Comma-separated caster ids, for example caster1,caster2,caster8")
    parser.add_argument("--all-casters", action="store_true")
    parser.add_argument("--validate-config", action="store_true")
    args = parser.parse_args()

    cfg = load_runtime_config()
    setup_logging(cfg)
    wf = ShiftWorkflow(cfg=cfg, selected_ids=_selected_ids_from_args(args))

    if args.validate_config:
        print(wf.validate_config())
        return

    if args.diagnosis_only and args.verified_only:
        parser.error("--diagnosis-only and --verified-only cannot be used together")

    if args.date and args.shift:
        run = ShiftRun(args.date, ShiftWorkflow._normalize_shift_name(args.shift))
    else:
        run = detect_shift_for_trigger(_now())
        if not run:
            logger.info("Not a scheduled shift time. Exiting.")
            return

    if args.verified_only:
        wf.run_verified_only(run)
    elif args.diagnosis_only:
        wf.run_diagnosis_only(run)
    else:
        wf.run(run)


if __name__ == "__main__":
    main()
