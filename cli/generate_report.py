import json
import os
import sys
import time
import traceback
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reports.pipes.pipe_exporter import PipeExporter
from reports.pipes.verified_pipes import VerifiedPipeExporter
from reports.video.video_generator import ShiftVideoGenerator
from reports.video.video_overlay import ShiftVideoOverlayGenerator
from reports.common.email_sender import EmailSender
from reports.common.gdrive_uploader import GDriveUploader


# ---------------- CONFIG + LOGGING -----------------

def load_runtime_config() -> dict:
    cfg_path = PROJECT_ROOT / "config" / "runtime.yaml"
    with open(cfg_path, "r") as f:
        return yaml.safe_load(f) or {}


def setup_logging(cfg: dict):
    level_name = (cfg.get("logging", {}) or {}).get("level", "INFO")
    level = getattr(logging, str(level_name).upper(), logging.INFO)

    # systemd already redirects stdout/stderr to your log file, so stream logging is fine.
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


cfg = {}
logger = logging.getLogger("reports-generator")


# ---------------- Shift Workflow Implementation -----------------

@dataclass(frozen=True)
class ShiftRun:
    date_str: str   # dd-mm-YYYY
    shift_name: str # Shift_A / Shift_B / Shift_C


def _now():
    return datetime.now()


def detect_shift_for_trigger(now: datetime) -> ShiftRun | None:
    """
    Trigger times:
      06:00 -> previous day Shift_C
      14:00 -> same day Shift_A
      22:00 -> same day Shift_B
    """
    h, m = now.hour, now.minute

    def in_window(target_h: int, target_m: int, minutes_slack: int = 5) -> bool:
        t = target_h * 60 + target_m
        x = h * 60 + m
        return t <= x <= (t + minutes_slack)

    if in_window(6, 0):
        date = (now - timedelta(days=1)).strftime("%d-%m-%Y")
        return ShiftRun(date, "Shift_C")

    if in_window(14, 0):
        date = now.strftime("%d-%m-%Y")
        return ShiftRun(date, "Shift_A")

    if in_window(22, 0):
        date = now.strftime("%d-%m-%Y")
        return ShiftRun(date, "Shift_B")

    return None


def backoff_retry(fn, *, tries=4, base_delay=2.0, what="operation"):
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt == tries:
                break
            sleep_s = base_delay * (2 ** (attempt - 1))
            logger.warning("%s failed (attempt %s/%s). Retrying in %.1fs. Error=%s",
                           what, attempt, tries, sleep_s, e)
            time.sleep(sleep_s)

    raise RuntimeError(f"{what} failed after {tries} tries: {last_err}") from last_err


class ShiftWorkflow:

    def __init__(self):
        self.root = PROJECT_ROOT
        self.cfg = cfg

        self.mailer = None
        self.uploader = GDriveUploader()

        self.state_dir = self.root / "outputs" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, run: ShiftRun) -> Path:
        key = f"{run.date_str.replace('-','')}_{run.shift_name.lower()}"
        return self.state_dir / f"{key}.json"

    def _load_state(self, run: ShiftRun) -> dict:
        p = self._state_path(run)
        if p.exists():
            return json.loads(p.read_text())
        return {}

    def _save_state(self, run: ShiftRun, data: dict):
        self._state_path(run).write_text(json.dumps(data, indent=2, sort_keys=True))

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
        }

        for key in list(state):
            if key in exact_keys or any(key.startswith(prefix) for prefix in prefixes):
                state.pop(key, None)

    def _mailer(self) -> EmailSender:
        if self.mailer is None:
            self.mailer = EmailSender()
        return self.mailer

    def _diagnosis_recipients(self) -> list[str]:
        recipients = (self.cfg.get("email", {}) or {}).get("diagnosis_recipients", []) or []
        if isinstance(recipients, str):
            recipients = [recipients]
        return [str(r).strip() for r in recipients if str(r).strip()]

    def _verified_pipes_mode(self) -> str:
        return str(
            self.cfg.get("verified_pipes_mode")
            or self.cfg.get("verfied_pipes_mode")
            or "loadcell"
        ).strip().lower()

    def _verified_pipe_records_recipients(self) -> list[str]:
        recipients = self.cfg.get("verified_pipe_records_recipients", []) or []
        if isinstance(recipients, str):
            recipients = [recipients]
        return [str(r).strip() for r in recipients if str(r).strip()]

    def _caster_number(self) -> str:
        value = (
            self.cfg.get("caster_number")
            or self.cfg.get("Caster number")
            or self.cfg.get("caster number")
        )
        return str(value).strip() if value is not None and str(value).strip() else "N/A"

    def _email_password_skip_reason(self) -> str | None:
        email_cfg = self.cfg.get("email", {}) or {}
        password_env = email_cfg.get("password_env")

        if password_env:
            if not os.getenv(password_env):
                return f"Email password environment variable {password_env} is not set"
            return None

        if not email_cfg.get("password"):
            return "No email.password or email.password_env configured"

        return None

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

        total_seconds = int(round(float(seconds)))
        if total_seconds < 0:
            total_seconds = abs(total_seconds)

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
        return (
            "Pipe checkpoint was not 1 and G2 was not open "
            f"within {window_text} from T-Origin"
        )

    def _missing_loadcell_video_cfg(self) -> dict:
        cfg = self.cfg.get("missing_loadcell_video", {}) or {}
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "pre_origin_seconds": self._parse_positive_int(
                cfg.get("pre_origin_seconds"),
                default=60,
                name="missing_loadcell_video.pre_origin_seconds",
            ),
            "clip_duration_seconds": self._parse_positive_int(
                cfg.get("clip_duration_seconds"),
                default=300,
                name="missing_loadcell_video.clip_duration_seconds",
            ),
            "delete_after_upload": bool(cfg.get("delete_after_upload", True)),
        }

    def _shift_window(self, run: ShiftRun) -> tuple[datetime, datetime]:
        shifts_cfg = self.cfg.get("history", {}).get("shifts", [])
        shifts = {s["name"].lower(): (s["start"], s["end"]) for s in shifts_cfg}
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
        if not text:
            return None

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
        parts = [p.strip() for p in f"{existing}, {new}".split(",") if p.strip()]
        return ", ".join(dict.fromkeys(parts))

    def _build_missing_loadcell_windows(
        self,
        run: ShiftRun,
        records: list[dict],
    ) -> tuple[list[dict], int]:
        video_cfg = self._missing_loadcell_video_cfg()
        shift_start, shift_end = self._shift_window(run)
        pre_origin = timedelta(seconds=video_cfg["pre_origin_seconds"])
        duration = timedelta(seconds=video_cfg["clip_duration_seconds"])

        windows = []
        skipped = 0

        for idx, record in enumerate(records, start=1):
            origin = self._parse_origin_time(
                record.get("origin_time") or record.get("origin_time_raw")
            )
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
            windows.append({
                "start": start,
                "end": end,
                "label": label,
            })

        windows = sorted(windows, key=lambda item: item["start"])
        if not windows:
            return [], skipped

        merged = [windows[0].copy()]
        for window in windows[1:]:
            current = merged[-1]
            if window["start"] <= current["end"]:
                current["end"] = max(current["end"], window["end"])
                current["label"] = self._merge_overlay_labels(current["label"], window["label"])
                continue
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

    def _skip_missing_loadcell_videos(self, run: ShiftRun, state: dict, reason: str):
        for kind in ("overlay", "normal"):
            state[f"missing_loadcell_{kind}_video_skipped"] = True
            state[f"missing_loadcell_{kind}_video_skip_reason"] = reason
        self._save_state(run, state)

    def _generate_missing_loadcell_videos(
        self,
        run: ShiftRun,
        state: dict,
        verified_summary: dict | None,
    ) -> tuple[str | None, str | None]:
        video_cfg = self._missing_loadcell_video_cfg()
        records = (verified_summary or {}).get("loadcell_missing_records", []) or []

        state["missing_loadcell_video_strategy"] = "merged_window_compilation_overlay_and_normal"
        state["missing_loadcell_video_record_count"] = len(records)

        if not video_cfg["enabled"]:
            self._skip_missing_loadcell_videos(run, state, "missing_loadcell_video.enabled is false")
            logger.info("Missing-loadcell videos skipped; disabled in config")
            return None, None

        if not records:
            self._skip_missing_loadcell_videos(run, state, "No loadcell-missing pipes")
            logger.info("Missing-loadcell videos skipped; no loadcell-missing pipes")
            return None, None

        windows, skipped = self._build_missing_loadcell_windows(run, records)
        state["missing_loadcell_overlay_window_count"] = len(windows)
        state["missing_loadcell_overlay_skipped_record_count"] = skipped
        state["missing_loadcell_overlay_windows"] = self._serialize_windows(windows)
        self._save_state(run, state)

        if not windows:
            self._skip_missing_loadcell_videos(run, state, "No valid loadcell-missing video windows")
            logger.warning("Missing-loadcell videos skipped; no valid windows")
            return None, None

        shift_key = run.shift_name.lower()
        output_name = (
            f"missing_loadcell_{run.date_str.replace('-', '')}_{shift_key}_overlay.mp4"
        )
        normal_output_name = (
            f"missing_loadcell_{run.date_str.replace('-', '')}_{shift_key}_normal.mp4"
        )
        shift_letter = run.shift_name.split("_")[1]

        overlay_gen = ShiftVideoOverlayGenerator(
            run.date_str,
            shift_letter,
            windows=windows,
            output_name=output_name,
            normal_output_name=normal_output_name,
        )
        overlay_path = backoff_retry(
            lambda: overlay_gen.generate(),
            what="Missing-loadcell overlay video generation",
        )
        normal_path = str(overlay_gen.normal_output_path)
        state["missing_loadcell_overlay_video_path"] = overlay_path
        state["missing_loadcell_normal_video_path"] = normal_path
        self._save_state(run, state)

        overlay_link = backoff_retry(
            lambda: self.uploader.upload_video(overlay_path),
            what="Drive upload missing-loadcell overlay video",
        )
        state["missing_loadcell_overlay_video_drive_link"] = overlay_link
        state["missing_loadcell_overlay_video_uploaded_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(run, state)
        logger.info("Missing-loadcell overlay video uploaded | link=%s", overlay_link)

        normal_link = backoff_retry(
            lambda: self.uploader.upload_video(normal_path),
            what="Drive upload missing-loadcell normal video",
        )
        state["missing_loadcell_normal_video_drive_link"] = normal_link
        state["missing_loadcell_normal_video_uploaded_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(run, state)
        logger.info("Missing-loadcell normal video uploaded | link=%s", normal_link)

        if video_cfg["delete_after_upload"]:
            for kind, path in (("overlay", overlay_path), ("normal", normal_path)):
                try:
                    Path(path).unlink(missing_ok=True)
                    state[f"missing_loadcell_{kind}_video_deleted_after_upload"] = True
                    self._save_state(run, state)
                    logger.info("Missing-loadcell %s video deleted after upload | %s", kind, path)
                except Exception as e:
                    state[f"missing_loadcell_{kind}_video_deleted_after_upload"] = False
                    self._save_state(run, state)
                    logger.warning(
                        "Failed to delete missing-loadcell %s video | %s | error=%s",
                        kind,
                        path,
                        e,
                    )

        return overlay_path, overlay_link

    def _generate_diagnosis_report(self, run: ShiftRun, state: dict) -> tuple[str, dict]:
        diagnosis_exporter = PipeExporter()
        diagnosis_path_obj, diagnosis_summary = backoff_retry(
            lambda: diagnosis_exporter.export_diagnosis(run.date_str, run.shift_name),
            what="Diagnosis XLSX export",
        )
        diagnosis_path = str(diagnosis_path_obj)

        state["diagnosis_xlsx_path"] = diagnosis_path
        state["diagnosis_summary"] = diagnosis_summary
        state["diagnosis_finished_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(run, state)
        return diagnosis_path, diagnosis_summary

    def _send_diagnosis_report(self, run: ShiftRun, state: dict, *, raise_on_error: bool = False):
        try:
            diagnosis_path, diagnosis_summary = self._generate_diagnosis_report(run, state)
            min_gap_label, max_gap_label = self._diagnosis_gap_labels(diagnosis_summary)

            subject = f"Pipe Diagnosis Report (XLSX) - {run.shift_name} - {run.date_str}"
            body = (
                f"Pipe Diagnosis Report\n\n"
                f"Date                       : {run.date_str}\n"
                f"Shift                      : {run.shift_name}\n"
                f"Pipe Count                 : {diagnosis_summary['pipe_count']}\n"
                f"Abnormal Rows              : {diagnosis_summary['abnormal_count']}\n"
                f"T-Origin Gap Abnormal      : {diagnosis_summary['t_origin_gap_abnormal_count']}\n"
                f"T-Origin Gap Above {max_gap_label}: {diagnosis_summary['t_origin_gap_too_slow_count']}\n"
                f"T-Origin Gap Below {min_gap_label}: {diagnosis_summary['t_origin_gap_too_fast_count']}\n"
                f"Loadcell Missing Rows      : {diagnosis_summary['loadcell_missing_count']}\n\n"
                f"Diagnosis Excel file attached. Abnormal rows are highlighted red.\n"
            )

            diagnosis_recipients = self._diagnosis_recipients()

            if not diagnosis_recipients:
                state["emailed_diagnosis_xlsx"] = False
                state["diagnosis_skip_reason"] = "No email.diagnosis_recipients configured"
                state["diagnosis_finished_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_state(run, state)
                logger.info("Diagnosis XLSX email skipped; no email.diagnosis_recipients configured")
                return

            password_skip_reason = self._email_password_skip_reason()
            if password_skip_reason:
                state["emailed_diagnosis_xlsx"] = False
                state["diagnosis_skip_reason"] = password_skip_reason
                state["diagnosis_finished_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_state(run, state)
                logger.warning(
                    "Diagnosis XLSX email skipped; %s | xlsx=%s",
                    password_skip_reason, diagnosis_path
                )
                return

            backoff_retry(
                lambda: self._mailer().send_csv(
                    subject,
                    body,
                    diagnosis_path,
                    recipients=diagnosis_recipients,
                ),
                what="Diagnosis XLSX email"
            )

            state["emailed_diagnosis_xlsx"] = True
            state["diagnosis_recipients"] = diagnosis_recipients
            state["diagnosis_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)

            logger.info(
                "Diagnosis XLSX email sent | abnormal=%s | recipients=%s | path=%s",
                diagnosis_summary["abnormal_count"], len(diagnosis_recipients), diagnosis_path
            )

        except Exception:
            state["status"] = "partial_failure"
            state["diagnosis_error"] = traceback.format_exc()
            state["diagnosis_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)
            logger.exception("Diagnosis XLSX email failed")
            if raise_on_error:
                raise

    def _send_verified_pipes_report(
        self,
        run: ShiftRun,
        state: dict,
        csv_path: str,
        *,
        raise_on_error: bool = False,
    ) -> tuple[str | None, dict | None]:
        try:
            verified_exporter = VerifiedPipeExporter()
            verified_path_obj, verified_summary = backoff_retry(
                lambda: verified_exporter.export(
                    run.date_str,
                    run.shift_name,
                    csv_path,
                    mode=self._verified_pipes_mode(),
                ),
                what="Verified pipes CSV export",
            )
            verified_path = str(verified_path_obj)

            state["verified_pipes_csv_path"] = verified_path
            state["verified_pipes_summary"] = verified_summary
            self._save_state(run, state)

            recipients = self._verified_pipe_records_recipients()
            if not recipients:
                state["emailed_verified_pipes"] = False
                state["verified_pipes_skip_reason"] = "No verified_pipe_records_recipients configured"
                state["verified_pipes_finished_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_state(run, state)
                logger.info("Verified pipes email skipped; no verified_pipe_records_recipients configured")
                return verified_path, verified_summary

            password_skip_reason = self._email_password_skip_reason()
            if password_skip_reason:
                state["emailed_verified_pipes"] = False
                state["verified_pipes_skip_reason"] = password_skip_reason
                state["verified_pipes_finished_at"] = datetime.now().isoformat(timespec="seconds")
                self._save_state(run, state)
                logger.warning(
                    "Verified pipes email skipped; %s | csv=%s",
                    password_skip_reason, verified_path
                )
                return verified_path, verified_summary

            subject = (
                f"Verified Pipe Records - {run.date_str} - {run.shift_name} - "
                f"Pipe Count {verified_summary['verified_count']}"
            )
            body = (
                f"Date                  : {run.date_str}\n"
                f"Caster number         : {self._caster_number()}\n"
                f"Shift                 : {run.shift_name}\n\n"
                f"Pipe Count            : {verified_summary['verified_count']}\n"
            )

            backoff_retry(
                lambda: self._mailer().send_csv(
                    subject,
                    body,
                    verified_path,
                    recipients=recipients,
                ),
                what="Verified pipes email",
            )

            state["emailed_verified_pipes"] = True
            state["verified_pipe_records_recipients"] = recipients
            state["verified_pipes_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)

            logger.info(
                "Verified pipes email sent | verified=%s | removed=%s | recipients=%s | path=%s",
                verified_summary["verified_count"],
                verified_summary["removed_count"],
                len(recipients),
                verified_path,
            )
            return verified_path, verified_summary

        except Exception:
            state["verified_pipes_error"] = traceback.format_exc()
            state["verified_pipes_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)
            logger.exception("Verified pipes email failed")
            if raise_on_error:
                raise
            return None, None

    def run_diagnosis_only(self, run: ShiftRun):
        state = self._load_state(run)
        state.update({
            "date": run.date_str,
            "shift": run.shift_name,
            "diagnosis_started_at": datetime.now().isoformat(timespec="seconds"),
            "status": "diagnosis_running",
        })
        self._save_state(run, state)

        logger.info("Diagnosis-only workflow start | date=%s | shift=%s", run.date_str, run.shift_name)
        self._send_diagnosis_report(run, state, raise_on_error=True)

        state["status"] = "success" if state.get("emailed_diagnosis_xlsx") else "partial_failure"
        state["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(run, state)
        logger.info("Diagnosis-only workflow finished | status=%s", state["status"])

    def run(self, run: ShiftRun):
        force = os.getenv("FORCE_RERUN") == "1"
        state = self._load_state(run)

        if state.get("status") == "success" and not force:
            logger.info("Already success for %s %s (use FORCE_RERUN=1 to rerun). Skipping.",
                        run.date_str, run.shift_name)
            return

        self._clear_previous_run_outputs(state)

        started_at = datetime.now().isoformat(timespec="seconds")
        state.update({
            "date": run.date_str,
            "shift": run.shift_name,
            "started_at": started_at,
            "status": "running",
        })
        self._save_state(run, state)

        csv_path = None
        csv_link = None
        verified_path = None
        verified_summary = None
        diagnosis_path = None
        diagnosis_summary = None
        missing_overlay_path = None
        missing_overlay_link = None
        normal_video_path = None
        pipe_count = 0
        csv_email_sent = False
        errors = []

        logger.info("Workflow start | date=%s | shift=%s", run.date_str, run.shift_name)

        #   CSV export
        try:
            exporter = PipeExporter()

            # IMPORTANT: exporter.export returns (path, pipe_count)
            csv_path_obj, pipe_count = backoff_retry(
                lambda: exporter.export(run.date_str, run.shift_name),
                what="CSV export"
            )
            csv_path = str(csv_path_obj)

            state["csv_path"] = csv_path
            state["pipe_count"] = pipe_count
            self._save_state(run, state)

            logger.info("CSV export success | pipe_count=%s | path=%s", pipe_count, csv_path)

        except Exception:
            msg = "CSV export failed:\n" + traceback.format_exc()
            errors.append(msg)
            logger.exception("CSV export failed")

        #  Email CSV (OPTIONAL via runtime.yaml)
        send_csv_attachment = bool((self.cfg.get("email", {}) or {}).get("send_csv_attachment", True))

        if csv_path and send_csv_attachment:
            try:
                subject = f"Pipe Report (CSV) - {run.shift_name} - {run.date_str}"
                body = (
                    f"Pipe Production Report\n\n"
                    f"Date       : {run.date_str}\n"
                    f"Shift      : {run.shift_name}\n"
                    f"Pipe Count : {pipe_count}\n\n"
                    f"CSV attached.\n"
                )

                backoff_retry(
                    lambda: self._mailer().send_csv(subject, body, csv_path),
                    what="Email CSV"
                )

                state["emailed_csv"] = True
                self._save_state(run, state)
                csv_email_sent = True

                logger.info("CSV email sent")

            except Exception:
                msg = "Email CSV failed:\n" + traceback.format_exc()
                errors.append(msg)
                logger.exception("Email CSV failed")
        else:
            logger.info("CSV attachment email skipped (send_csv_attachment=%s).", send_csv_attachment)

        #  Verified pipe CSV email. This must run after the raw CSV mail and before video generation.
        if csv_path and csv_email_sent:
            try:
                verified_path, verified_summary = self._send_verified_pipes_report(
                    run,
                    state,
                    csv_path,
                    raise_on_error=True,
                )
            except Exception:
                msg = "Verified pipes email failed:\n" + traceback.format_exc()
                errors.append(msg)
                logger.exception("Verified pipes email failed")
        elif csv_path:
            state["emailed_verified_pipes"] = False
            state["verified_pipes_skip_reason"] = "Raw CSV email was not sent"
            state["verified_pipes_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)

        #  Upload CSV
        if csv_path:
            try:
                csv_link = backoff_retry(
                    lambda: self.uploader.upload_csv(csv_path),
                    what="Drive upload CSV"
                )
                state["csv_drive_link"] = csv_link
                self._save_state(run, state)
                logger.info("CSV uploaded | link=%s", csv_link)

               # DELETE CSV AFTER SUCCESSFUL UPLOAD
                try:
                    Path(csv_path).unlink(missing_ok=True)
                    logger.info("CSV deleted after upload | %s", csv_path)
                except Exception as e:
                    logger.warning("Failed to delete CSV | %s | error=%s", csv_path, e)
            except Exception:
                msg = "Drive upload CSV failed:\n" + traceback.format_exc()
                errors.append(msg)
                logger.exception("Drive upload CSV failed")

        #  Generate and upload one merged overlay + normal video for loadcell-missing pipes.
        if verified_summary:
            try:
                missing_overlay_path, missing_overlay_link = self._generate_missing_loadcell_videos(
                    run,
                    state,
                    verified_summary,
                )
            except Exception:
                msg = "Missing-loadcell video generation/upload failed:\n" + traceback.format_exc()
                errors.append(msg)
                state["missing_loadcell_video_error"] = traceback.format_exc()
                self._save_state(run, state)
                logger.exception("Missing-loadcell video generation/upload failed")
        elif csv_path:
            self._skip_missing_loadcell_videos(run, state, "Verified pipe summary unavailable")

        #  Generate diagnosis report before the final Drive-link email.
        try:
            diagnosis_path, diagnosis_summary = self._generate_diagnosis_report(run, state)
            logger.info("Diagnosis XLSX generated | path=%s", diagnosis_path)
        except Exception:
            msg = "Diagnosis XLSX export failed:\n" + traceback.format_exc()
            errors.append(msg)
            state["diagnosis_error"] = traceback.format_exc()
            state["diagnosis_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)
            logger.exception("Diagnosis XLSX export failed")

        # Final summary email with video link plus diagnosis and verified-report details.
        try:
            subject = f"Pipe Recordings - {run.shift_name} - {run.date_str}"
            verified_count = (
                verified_summary.get("verified_count")
                if verified_summary
                else "N/A"
            )
            removed_count = (
                verified_summary.get("removed_count")
                if verified_summary
                else "N/A"
            )
            loadcell_missing_count = (
                verified_summary.get("loadcell_missing_count")
                if verified_summary
                else "N/A"
            )
            removed_reason = self._removed_pipe_reason(verified_summary)
            min_gap_label, max_gap_label = self._diagnosis_gap_labels(diagnosis_summary)
            overlay_skip_reason = state.get("missing_loadcell_overlay_video_skip_reason")
            overlay_link_text = missing_overlay_link or state.get("missing_loadcell_overlay_video_drive_link") or (
                f"N/A ({overlay_skip_reason})" if overlay_skip_reason else "N/A"
            )
            normal_skip_reason = state.get("missing_loadcell_normal_video_skip_reason") or overlay_skip_reason
            normal_link_text = state.get("missing_loadcell_normal_video_drive_link") or (
                f"N/A ({normal_skip_reason})" if normal_skip_reason else "N/A"
            )
            diagnosis_summary = diagnosis_summary or {}
            attachments = []
            if diagnosis_path and Path(diagnosis_path).exists():
                attachments.append(diagnosis_path)

            body_lines = [
                "Pipe Production Recordings",
                "",
                f"Date                         : {run.date_str}",
                f"Caster number                : {self._caster_number()}",
                f"Shift                        : {run.shift_name}",
                f"Raw Pipe Count               : {pipe_count}",
                f"Verified Pipe Count          : {verified_count}",
                f"Removed Pipe Count           : {removed_count}",
                f"Removed Pipe Reason          : {removed_reason}",
                f"Loadcell Missing Pipe Count  : {loadcell_missing_count}",
                "",
                "Drive Links",
                f"Raw CSV link                 : {csv_link or 'N/A'}",
                f"Missing Loadcell Overlay link: {overlay_link_text}",
                f"Missing Loadcell Normal link : {normal_link_text}",
                f"Missing Video Strategy       : one merged window compilation",
                "",
                "Diagnosis Report",
                f"Diagnosis XLSX               : {'attached' if attachments else 'N/A'}",
                f"Diagnosis Pipe Count         : {diagnosis_summary.get('pipe_count', 'N/A')}",
                f"Diagnosis Abnormal Rows      : {diagnosis_summary.get('abnormal_count', 'N/A')}",
                f"Diagnosis T-Origin Gap Above {max_gap_label}: {diagnosis_summary.get('t_origin_gap_too_slow_count', 'N/A')}",
                f"Diagnosis T-Origin Gap Below {min_gap_label}: {diagnosis_summary.get('t_origin_gap_too_fast_count', 'N/A')}",
                f"Diagnosis Loadcell Missing   : {diagnosis_summary.get('loadcell_missing_count', 'N/A')}",
                "",
            ]

            if errors:
                body_lines += ["Some steps failed:", "", *errors]
                logger.warning("Workflow has errors before normal video generation.")
            else:
                logger.info("Final summary ready with no prior errors.")

            state["status"] = "final_email_running"
            self._save_state(run, state)

            backoff_retry(
                lambda: self._mailer().send(
                    subject,
                    "\n".join(body_lines),
                    attachments=attachments,
                ),
                what="Final email"
            )

            state["final_summary_email_sent"] = True
            state["final_summary_email_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)
            logger.info("Final summary email sent")

        except Exception:
            msg = "Final email failed:\n" + traceback.format_exc()
            errors.append(msg)
            state["final_summary_email_sent"] = False
            state["final_summary_email_error"] = traceback.format_exc()
            state["final_summary_email_finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._save_state(run, state)
            logger.exception("Final email failed")

        #  Generate the normal full-shift video locally only. Do not upload it to Drive.
        try:
            video_gen = ShiftVideoGenerator(
                run.date_str,
                run.shift_name.split("_")[1],
            )
            normal_video_path = backoff_retry(
                lambda: video_gen.generate(),
                what="Normal shift video generation",
            )
            state["normal_shift_video_path"] = normal_video_path
            state["normal_shift_video_uploaded"] = False
            state["video_path"] = normal_video_path
            state["video_drive_link"] = None
            self._save_state(run, state)
            logger.info("Normal full-shift video generated locally | path=%s", normal_video_path)
        except Exception:
            msg = "Normal shift video generation failed:\n" + traceback.format_exc()
            errors.append(msg)
            state["normal_shift_video_error"] = traceback.format_exc()
            self._save_state(run, state)
            logger.exception("Normal shift video generation failed")

        state["status"] = "partial_failure" if errors else "success"
        state["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_state(run, state)
        logger.info("Workflow finished | status=%s", state["status"])


import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--shift")
    parser.add_argument("--diagnosis-only", action="store_true")
    args = parser.parse_args()

    wf = ShiftWorkflow()

    if args.date and args.shift:
        s = args.shift.strip()

        # Accept: A/B/C, a/b/c
        s_upper = s.upper()
        if s_upper in {"A", "B", "C"}:
            shift_name = f"Shift_{s_upper}"
        else:
            raise ValueError("Invalid shift. Use A, B, or C")

        run = ShiftRun(args.date, shift_name)
        if args.diagnosis_only:
            wf.run_diagnosis_only(run)
        else:
            wf.run(run)
        return

    now = _now()
    run = detect_shift_for_trigger(now)
    if not run:
        logger.info("Not a scheduled shift time. Exiting.")
        return

    if args.diagnosis_only:
        wf.run_diagnosis_only(run)
    else:
        wf.run(run)


from cli.report_workflow import (  # noqa: E402,F401
    ShiftRun,
    ShiftWorkflow,
    backoff_retry,
    detect_shift_for_trigger,
    main,
    setup_logging,
)


if __name__ == "__main__":
    main()
