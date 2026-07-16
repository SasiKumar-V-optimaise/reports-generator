"""Immutable application configuration models.

YAML is an infrastructure detail.  The rest of the application receives only
the models in this module; no nested configuration dictionaries escape the
loader.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time, timedelta
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PathsConfig:
    output_root: Path
    state_root: Path
    temp_root: Path
    log_root: Path


@dataclass(frozen=True, slots=True)
class ShiftConfig:
    """A configured production shift.

    ``name`` is the canonical upper-case letter (``A``, ``B`` or ``C``).
    """

    name: str
    start: time
    end: time

    @property
    def crosses_midnight(self) -> bool:
        return self.end <= self.start


@dataclass(frozen=True, slots=True)
class CasterConfig:
    id: str
    display_name: str
    active: bool
    database_directory: Path
    database_file: str
    history_directory: Path
    recording_directory: Path
    roi_path: Path
    number: int | str | None = None

    @property
    def enabled(self) -> bool:
        """Compatibility spelling for callers migrating from ``enabled``."""

        return self.active

    @property
    def database_path(self) -> Path:
        return self.database_directory / self.database_file


@dataclass(frozen=True, slots=True)
class VideoResolution:
    """Video dimensions; ``None`` means preserve the source dimension."""

    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class VideoOverlayConfig:
    font_scale: float = 0.7
    thickness: int = 2
    color: tuple[int, int, int] = (0, 255, 255)
    margin_bottom: int = 20
    margin_left: int = 20


@dataclass(frozen=True, slots=True)
class VideoConfig:
    resolution: VideoResolution
    fps: float
    codec: str
    input_images_have_overlay: bool = False
    overlay: VideoOverlayConfig = VideoOverlayConfig()


@dataclass(frozen=True, slots=True)
class DiagnosisConfig:
    t_origin_gap_min: timedelta
    t_origin_gap_max: timedelta


@dataclass(frozen=True, slots=True)
class VerificationConfig:
    mode: str
    gate_open_max_interval: timedelta


@dataclass(frozen=True, slots=True)
class MissingLoadcellVideoConfig:
    enabled: bool
    pre_origin: timedelta
    clip_duration: timedelta
    delete_after_upload: bool


@dataclass(frozen=True, slots=True)
class GateCoverageConfig:
    interval: timedelta
    recent_window: timedelta
    minimum_average_percent: float
    roi_name: str
    gate_class_id: int
    source_resolution: VideoResolution
    alert_on_no_samples: bool = False
    send_email: bool = True


@dataclass(frozen=True, slots=True)
class EmailConfig:
    smtp_host: str
    smtp_port: int
    sender: str
    password_env: str
    recipients: tuple[str, ...]
    test_recipients: tuple[str, ...] = ()
    diagnosis_recipients: tuple[str, ...] = ()
    send_csv_attachment: bool = True
    use_starttls: bool = True
    timeout_seconds: float = 30.0

    @property
    def smtp_server(self) -> str:
        """Compatibility spelling used by the previous configuration."""

        return self.smtp_host


@dataclass(frozen=True, slots=True)
class UploadConfig:
    remote: str
    base_path: str
    csv_directory: str
    videos_directory: str
    chunk_size: str = "128M"
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class VideoRetentionConfig:
    keep_days: int
    include_overlay_videos: bool = True


@dataclass(frozen=True, slots=True)
class StorageConfig:
    threshold_percent: int
    recipient_mode: str = "test"
    device: str | None = None
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    level: str = "INFO"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 10


@dataclass(frozen=True, slots=True)
class AppConfig:
    project_root: Path
    paths: PathsConfig
    casters: tuple[CasterConfig, ...]
    shifts: tuple[ShiftConfig, ...]
    video: VideoConfig
    diagnosis: DiagnosisConfig
    verification: VerificationConfig
    missing_loadcell_video: MissingLoadcellVideoConfig
    gate_coverage: GateCoverageConfig
    email: EmailConfig
    upload: UploadConfig
    video_retention: VideoRetentionConfig
    storage: StorageConfig
    logging: LoggingConfig
    selected_caster_ids: tuple[str, ...] = ()

    @property
    def active_casters(self) -> tuple[CasterConfig, ...]:
        selected = frozenset(self.selected_caster_ids)
        return tuple(
            caster
            for caster in self.casters
            if caster.active and (not selected or caster.id in selected)
        )

    @property
    def enabled_casters(self) -> tuple[CasterConfig, ...]:
        return self.active_casters

    def caster(self, caster_id: str) -> CasterConfig:
        for caster in self.casters:
            if caster.id == caster_id:
                return caster
        raise KeyError(f"Unknown caster id: {caster_id}")

    def with_selected_casters(self, caster_ids: tuple[str, ...]) -> AppConfig:
        return replace(self, selected_caster_ids=caster_ids)
