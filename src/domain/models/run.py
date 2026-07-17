from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.domain.models.caster import CasterConfig


@dataclass(frozen=True)
class ShiftRun:
    date_str: str
    shift_name: str


@dataclass(frozen=True)
class OutputPaths:
    raw_csv_dir: Path
    verified_csv_dir: Path
    diagnosis_dir: Path
    video_dir: Path
    overlay_video_dir: Path
    logs_dir: Path
    state_dir: Path


@dataclass(frozen=True)
class ArtifactResult:
    path: Path | None = None
    drive_link: str | None = None
    exported: bool = False
    uploaded: bool = False
    deleted_after_upload: bool = False


@dataclass(frozen=True)
class VerificationSummary:
    input_count: int = 0
    verified_count: int = 0
    removed_count: int = 0
    loadcell_missing_count: int = 0
    loadcell_missing_records: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class DiagnosisSummary:
    pipe_count: int = 0
    abnormal_count: int = 0
    loadcell_missing_count: int = 0


@dataclass(frozen=True)
class VideoWindow:
    start: datetime
    end: datetime
    label: str


@dataclass
class CasterRunResult:
    caster: CasterConfig
    state: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    csv_path: str | None = None
    csv_drive_link: str | None = None
    pipe_count: int | str = 0
    raw_exported: bool = False
    raw_email_sent: bool = False
    verified_path: str | None = None
    verified_summary: dict | None = None
    verified_exported: bool = False
    diagnosis_path: str | None = None
    diagnosis_summary: dict | None = None
    diagnosis_exported: bool = False
    missing_overlay_link: str | None = None
    missing_normal_link: str | None = None
    full_shift_video_path: str | None = None


