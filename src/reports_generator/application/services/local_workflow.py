"""Concrete local report and video stages used by the CLI composition root.

External delivery and destructive cleanup intentionally remain outside these
services. A `--test` run can therefore exercise production readers, domain
rules, report writers, and video encoding without sending or deleting data.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, cast

import cv2

from reports_generator.application.models import (
    Artifact,
    ArtifactType,
    StageResult,
    WorkflowRequest,
)
from reports_generator.domain.pipes import (
    GateOpening,
    PipeRecord,
    diagnose_pipes,
    format_duration,
    verify_pipes,
)
from reports_generator.domain.shifts import (
    Shift,
    ShiftDefinition,
    ShiftWindow,
    calculate_shift_window,
)
from reports_generator.domain.videos import (
    FrameCandidate,
    PipeCountEvent,
    SelectedFrame,
    VideoWindow,
    parse_frame_timestamp,
    pipe_count_for_frame,
    select_frames,
)
from reports_generator.infrastructure.config.models import AppConfig
from reports_generator.infrastructure.database import (
    PIPE_COLUMNS,
    PipeRecord as DatabasePipeRecord,
    SQLiteGateReader,
    SQLitePipeReader,
)
from reports_generator.infrastructure.reports import CsvReportWriter, DiagnosisXlsxWriter
from reports_generator.infrastructure.video import (
    Frame,
    OpenCvFrameWriter,
    OverlayRenderer,
    TextOverlay,
)
from reports_generator.shared.paths import OutputPathBuilder

IST = timezone(timedelta(hours=5, minutes=30), name="IST")
_IMAGE_EXTENSIONS = ("*.jpeg", "*.jpg", "*.png")


class WorkflowContext(Protocol):
    request: WorkflowRequest
    caster_id: str
    stages: list[StageResult]


def _shift_window(config: AppConfig, request: WorkflowRequest) -> ShiftWindow:
    definitions = tuple(
        ShiftDefinition(Shift.parse(item.name), item.start, item.end) for item in config.shifts
    )
    return calculate_shift_window(request.production_date, request.shift, definitions)


def _epoch(value: datetime) -> float:
    """Interpret configured production clocks as IST before querying Unix epochs."""

    return value.replace(tzinfo=IST).timestamp()


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(IST).replace(tzinfo=None)
    return parsed


def _checkpoint(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "0", "false", "no", "none", "null"}:
            return False
        if normalized in {"1", "true", "yes"}:
            return True
    return bool(value)


def _domain_pipe(record: DatabasePipeRecord) -> PipeRecord:
    origin = _parse_datetime(record.t_origin)
    if origin is None:
        raise ValueError(f"pipe {record.pipe_uid!r} has no valid t_origin")
    return PipeRecord(
        pipe_uid=str(record.pipe_uid),
        origin_time=origin,
        loadcell_enter=_parse_datetime(record.t_loadcell_enter),
        loadcell_exit=_parse_datetime(record.t_loadcell_exit),
        checkpoint=_checkpoint(record.pipe_checkpoint),
    )


def _domain_gate(gate_name: str, timestamp: object) -> GateOpening | None:
    parsed = _parse_datetime(timestamp)
    return None if parsed is None else GateOpening(parsed, gate_name)


class LocalReportService:
    """Read one caster's SQLite data and create all tabular shift artifacts."""

    def __init__(self, config: AppConfig, paths: OutputPathBuilder | None = None) -> None:
        self.config = config
        self.paths = paths or OutputPathBuilder(config.paths.output_root)
        self.csv_writer = CsvReportWriter()
        self.diagnosis_writer = DiagnosisXlsxWriter()

    def generate(self, context: WorkflowContext) -> StageResult:
        request = context.request
        caster = self.config.caster(context.caster_id)
        window = _shift_window(self.config, request)
        # Reader queries are inclusive. Subtract a microsecond to preserve the
        # domain's half-open shift window and avoid including the next shift.
        start_timestamp = _epoch(window.start)
        end_timestamp = _epoch(window.end) - 0.000001

        raw_records = SQLitePipeReader(caster.database_path).read(
            start_timestamp, end_timestamp
        )
        domain_records = tuple(_domain_pipe(record) for record in raw_records)

        raw_path = self.paths.raw_csv_path(
            context.caster_id, request.production_date, request.shift
        )
        self.csv_writer.write(
            raw_path,
            (record.as_dict() for record in raw_records),
            fieldnames=PIPE_COLUMNS,
        )

        gate_result = SQLiteGateReader(caster.database_path).read(
            start_timestamp, end_timestamp
        )
        gate_openings = tuple(
            opening
            for opening in (
                _domain_gate(record.gate_name, record.t_open_ist) for record in gate_result
            )
            if opening is not None
        )
        verification = verify_pipes(
            domain_records,
            gate_openings,
            mode=self.config.verification.mode,
            shift_end=window.end,
            max_interval=self.config.verification.gate_open_max_interval,
        )

        verified_indices = [
            index for index, decision in enumerate(verification.decisions) if decision.verified
        ]
        chronological = sorted(
            verified_indices,
            key=lambda index: (domain_records[index].origin_time, index),
        )
        pipe_numbers = {index: number for number, index in enumerate(chronological, start=1)}
        verified_rows = []
        for index in verified_indices:
            decision = verification.decisions[index]
            verified_rows.append(
                {
                    "pipe_number": pipe_numbers[index],
                    **raw_records[index].as_dict(),
                    "verification_reason": decision.reason.value,
                }
            )

        verified_columns = ("pipe_number", *PIPE_COLUMNS, "verification_reason")
        verified_path = self.paths.verified_csv_path(
            context.caster_id, request.production_date, request.shift
        )
        self.csv_writer.write(
            verified_path,
            verified_rows,
            fieldnames=verified_columns,
        )

        raw_by_domain_id = {
            id(domain_record): raw_record
            for domain_record, raw_record in zip(domain_records, raw_records)
        }
        diagnosis_rows = []
        for diagnosis in diagnose_pipes(
            domain_records,
            min_gap=self.config.diagnosis.t_origin_gap_min,
            max_gap=self.config.diagnosis.t_origin_gap_max,
        ):
            raw = raw_by_domain_id[id(diagnosis.pipe)]
            diagnosis_rows.append(
                {
                    **raw.as_dict(),
                    "next_pipe_uid": diagnosis.next_pipe_uid,
                    "t_origin_gap": format_duration(diagnosis.origin_gap),
                    "t_origin_gap_seconds": (
                        diagnosis.origin_gap.total_seconds()
                        if diagnosis.origin_gap is not None
                        else None
                    ),
                    "t_origin_gap_status": diagnosis.gap_status.value,
                    "loadcell_status": diagnosis.loadcell_status.value,
                    "diagnosis_status": diagnosis.status.value,
                    "diagnosis_reason": diagnosis.diagnosis_reason,
                    "highlight_color": diagnosis.highlight_color,
                }
            )
        diagnosis_columns = (
            *PIPE_COLUMNS,
            "next_pipe_uid",
            "t_origin_gap",
            "t_origin_gap_seconds",
            "t_origin_gap_status",
            "loadcell_status",
            "diagnosis_status",
            "diagnosis_reason",
            "highlight_color",
        )
        diagnosis_path = self.paths.diagnosis_path(
            context.caster_id, request.production_date, request.shift
        )
        self.diagnosis_writer.write(
            diagnosis_path,
            diagnosis_rows,
            columns=diagnosis_columns,
        )

        warnings: list[str] = []
        if not raw_records:
            warnings.append("no pipe records were found in the selected shift")
        if gate_result.source_table is None:
            warnings.append("no compatible gate event table was found; verification used no gates")

        return StageResult(
            "report",
            True,
            artifacts=(
                Artifact(ArtifactType.RAW_CSV, context.caster_id, raw_path),
                Artifact(ArtifactType.VERIFIED_CSV, context.caster_id, verified_path),
                Artifact(ArtifactType.DIAGNOSIS, context.caster_id, diagnosis_path),
            ),
            warnings=tuple(warnings),
        )


class LocalVideoService:
    """Encode the configured caster's saved shift frames into an MP4 artifact."""

    def __init__(self, config: AppConfig, paths: OutputPathBuilder | None = None) -> None:
        self.config = config
        self.paths = paths or OutputPathBuilder(config.paths.output_root)
        self.renderer = OverlayRenderer()

    def generate(self, context: WorkflowContext) -> StageResult:
        request = context.request
        caster = self.config.caster(context.caster_id)
        shift_window = _shift_window(self.config, request)
        candidates, searched = self._collect_candidates(caster.history_directory, shift_window)
        selected = select_frames(
            candidates,
            (VideoWindow(shift_window.start, shift_window.end - timedelta(microseconds=1)),),
        )
        if not selected:
            searched_text = ", ".join(str(path) for path in searched)
            raise RuntimeError(f"no shift images found; searched: {searched_text}")

        first_path, first_frame = self._first_readable(selected)
        source_height, source_width = first_frame.shape[:2]
        output_width = self.config.video.resolution.width or source_width
        output_height = self.config.video.resolution.height or source_height
        output_size = (output_width, output_height)
        output_path = self.paths.video_path(
            context.caster_id, request.production_date, request.shift
        )
        pipe_events = self._pipe_events(context)

        unreadable = 0
        written = 0
        with OpenCvFrameWriter(
            output_path,
            fps=self.config.video.fps,
            frame_size=output_size,
            codec=self.config.video.codec,
        ) as writer:
            for item in selected:
                path = Path(item.frame.identifier)
                frame = first_frame if path == first_path else cv2.imread(str(path))
                if frame is None:
                    unreadable += 1
                    continue
                if (frame.shape[1], frame.shape[0]) != output_size:
                    frame = cv2.resize(frame, output_size)
                frame = self._render_overlays(frame, item.frame.timestamp, pipe_events)
                writer.write(frame)
                written += 1

        if written == 0:
            output_path.unlink(missing_ok=True)
            raise RuntimeError("no readable frames were written to the shift video")

        warnings = (f"skipped {unreadable} unreadable image(s)",) if unreadable else ()
        return StageResult(
            "video",
            True,
            artifacts=(Artifact(ArtifactType.VIDEO, context.caster_id, output_path),),
            warnings=warnings,
        )

    @staticmethod
    def _collect_candidates(
        history_root: Path,
        window: ShiftWindow,
    ) -> tuple[tuple[FrameCandidate, ...], tuple[Path, ...]]:
        days = tuple(
            dict.fromkeys(
                (
                    window.start.date(),
                    (window.end - timedelta(microseconds=1)).date(),
                )
            )
        )
        directories = tuple(
            history_root / day.strftime("%Y_%m_%d") / f"Shift_{window.shift.value}_img"
            for day in days
        )
        frames: list[FrameCandidate] = []
        for day, directory in zip(days, directories):
            for pattern in _IMAGE_EXTENSIONS:
                for path in directory.glob(pattern):
                    timestamp = parse_frame_timestamp(path.name)
                    if timestamp is not None:
                        frames.append(FrameCandidate(timestamp, str(path), source_date=day))
        return tuple(frames), directories

    @staticmethod
    def _first_readable(selected: Iterable[SelectedFrame]) -> tuple[Path, Frame]:
        for item in selected:
            path = Path(item.frame.identifier)
            decoded = cv2.imread(str(path))
            if decoded is not None:
                return path, cast(Frame, decoded)
        raise RuntimeError("shift images were found, but none could be decoded")

    def _render_overlays(
        self,
        frame: Frame,
        timestamp: datetime,
        pipe_events: tuple[PipeCountEvent, ...],
    ) -> Frame:
        height = frame.shape[0]
        overlay = self.config.video.overlay
        texts: list[TextOverlay] = []
        if not self.config.video.input_images_have_overlay:
            texts.append(
                TextOverlay(
                    timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    (overlay.margin_left, max(15, height - overlay.margin_bottom)),
                    color=overlay.color,
                    scale=overlay.font_scale,
                    thickness=overlay.thickness,
                )
            )
        count = pipe_count_for_frame(timestamp, pipe_events)
        if count is not None:
            texts.append(
                TextOverlay(
                    f"Pipe Count: {count}",
                    (overlay.margin_left, min(max(15, height // 3), 35)),
                    color=overlay.color,
                    scale=overlay.font_scale,
                    thickness=overlay.thickness,
                )
            )
        return self.renderer.render(frame, texts=texts, copy=False)

    @staticmethod
    def _pipe_events(context: WorkflowContext) -> tuple[PipeCountEvent, ...]:
        verified_path = next(
            (
                artifact.path
                for stage in context.stages
                for artifact in stage.artifacts
                if artifact.artifact_type is ArtifactType.VERIFIED_CSV
            ),
            None,
        )
        if verified_path is None or not verified_path.is_file():
            return ()
        events: list[PipeCountEvent] = []
        with verified_path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                timestamp = _parse_datetime(row.get("t_origin"))
                try:
                    count = int(str(row.get("pipe_number", "")).strip())
                except ValueError:
                    continue
                if timestamp is not None and count > 0:
                    events.append(PipeCountEvent(timestamp, count))
        return tuple(events)


class LocalUploadService:
    def upload(self, context: WorkflowContext) -> StageResult:
        reason = (
            "external upload skipped in --test mode"
            if context.request.test_mode
            else "external upload adapter is not configured; local artifacts were retained"
        )
        return StageResult("upload", True, warnings=(reason,))


class LocalNotificationService:
    def notify(self, context: WorkflowContext) -> StageResult:
        reason = (
            "external notification skipped in --test mode"
            if context.request.test_mode
            else "external notification adapter is not configured"
        )
        return StageResult("notification", True, warnings=(reason,))


class LocalCleanupService:
    def cleanup(self, context: WorkflowContext) -> StageResult:
        reason = (
            "source cleanup skipped in --test mode"
            if context.request.test_mode
            else "source cleanup adapter is not configured; source images were retained"
        )
        return StageResult("cleanup", True, warnings=(reason,))
