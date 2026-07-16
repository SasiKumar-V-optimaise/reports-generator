"""Validation for fully parsed application configuration."""

from __future__ import annotations

import re
from pathlib import Path

from .models import AppConfig, CasterConfig, VideoResolution

_CASTER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigValidationError(ValueError):
    """Raised when configuration is syntactically valid YAML but unusable."""


def validate_config(config: AppConfig) -> None:
    errors: list[str] = []

    _validate_root_paths(config, errors)
    _validate_casters(config.casters, errors)
    _validate_shifts(config, errors)
    _validate_video(config, errors)

    if config.diagnosis.t_origin_gap_min.total_seconds() < 0:
        errors.append("diagnosis.t_origin_gap_min cannot be negative")
    if config.diagnosis.t_origin_gap_max < config.diagnosis.t_origin_gap_min:
        errors.append("diagnosis.t_origin_gap_max must be >= t_origin_gap_min")
    if config.verification.mode not in {"loadcell", "all"}:
        errors.append("verification.mode must be 'loadcell' or 'all'")
    if config.verification.gate_open_max_interval.total_seconds() <= 0:
        errors.append("verification.gate_open_max_interval must be greater than zero")

    missing_video = config.missing_loadcell_video
    if missing_video.pre_origin.total_seconds() < 0:
        errors.append("missing_loadcell_video.pre_origin cannot be negative")
    if missing_video.clip_duration.total_seconds() <= 0:
        errors.append("missing_loadcell_video.clip_duration must be greater than zero")

    gate = config.gate_coverage
    if gate.interval.total_seconds() <= 0:
        errors.append("gate_coverage.interval must be greater than zero")
    if gate.recent_window.total_seconds() <= 0:
        errors.append("gate_coverage.recent_window must be greater than zero")
    if not 0 <= gate.minimum_average_percent <= 100:
        errors.append("gate_coverage.minimum_average_percent must be between 0 and 100")
    if not gate.roi_name.strip():
        errors.append("gate_coverage.roi_name cannot be blank")
    if gate.gate_class_id < 0:
        errors.append("gate_coverage.gate_class_id cannot be negative")
    _validate_resolution(gate.source_resolution, "gate_coverage.source_resolution", errors)

    email = config.email
    if not email.smtp_host.strip():
        errors.append("email.smtp_host cannot be blank")
    if not 1 <= email.smtp_port <= 65535:
        errors.append("email.smtp_port must be between 1 and 65535")
    if not email.sender.strip():
        errors.append("email.sender cannot be blank")
    if not email.password_env.strip():
        errors.append("email.password_env cannot be blank")
    if email.timeout_seconds <= 0:
        errors.append("email.timeout_seconds must be greater than zero")
    for address in (
        email.sender,
        *email.recipients,
        *email.test_recipients,
        *email.diagnosis_recipients,
    ):
        if address and ("@" not in address or any(char.isspace() for char in address)):
            errors.append(f"invalid email address: {address!r}")

    upload = config.upload
    if upload.enabled and not upload.remote.strip():
        errors.append("upload.remote cannot be blank when uploads are enabled")
    if upload.enabled and not upload.base_path.strip(" /"):
        errors.append("upload.base_path cannot be blank when uploads are enabled")
    if not upload.chunk_size.strip():
        errors.append("upload.chunk_size cannot be blank")

    if config.video_retention.keep_days < 1:
        errors.append("video_retention.keep_days must be greater than zero")
    if not 1 <= config.storage.threshold_percent <= 100:
        errors.append("storage.threshold_percent must be between 1 and 100")
    if config.storage.recipient_mode not in {"test", "production"}:
        errors.append("storage.recipient_mode must be 'test' or 'production'")
    if not config.storage.device and config.storage.path is None:
        errors.append("storage must define either device or path")
    if config.logging.level not in _LOG_LEVELS:
        errors.append(f"logging.level must be one of {', '.join(sorted(_LOG_LEVELS))}")
    if config.logging.max_bytes < 1:
        errors.append("logging.max_bytes must be greater than zero")
    if config.logging.backup_count < 0:
        errors.append("logging.backup_count cannot be negative")

    _validate_selection(config, errors)
    if errors:
        raise ConfigValidationError("Invalid configuration:\n- " + "\n- ".join(errors))


def validate_selection(config: AppConfig, selected_caster_ids: tuple[str, ...]) -> None:
    candidate = config.with_selected_casters(selected_caster_ids)
    errors: list[str] = []
    _validate_selection(candidate, errors)
    if errors:
        raise ConfigValidationError("Invalid caster selection:\n- " + "\n- ".join(errors))


def _validate_root_paths(config: AppConfig, errors: list[str]) -> None:
    if not config.project_root.is_absolute():
        errors.append("project_root must be absolute")
    for name in ("output_root", "state_root", "temp_root", "log_root"):
        value = getattr(config.paths, name)
        if not value.is_absolute():
            errors.append(f"paths.{name} must resolve to an absolute path")


def _validate_casters(casters: tuple[CasterConfig, ...], errors: list[str]) -> None:
    if not casters:
        errors.append("casters must contain at least one caster")
        return

    seen: set[str] = set()
    for index, caster in enumerate(casters):
        prefix = f"casters[{index}]"
        if not _CASTER_ID.fullmatch(caster.id):
            errors.append(
                f"{prefix}.id must contain only letters, digits, underscores or hyphens "
                "and cannot start with punctuation"
            )
        if caster.id in seen:
            errors.append(f"duplicate caster id: {caster.id}")
        seen.add(caster.id)
        if not caster.display_name.strip():
            errors.append(f"{prefix}.display_name cannot be blank")
        if not caster.database_file or Path(caster.database_file).name != caster.database_file:
            errors.append(f"{prefix}.database_file must be a filename, not a path")
        for name in ("database_directory", "history_directory", "recording_directory", "roi_path"):
            path = getattr(caster, name)
            if not path.is_absolute():
                errors.append(f"{prefix}.{name} must resolve to an absolute path")


def _validate_shifts(config: AppConfig, errors: list[str]) -> None:
    names = [shift.name for shift in config.shifts]
    if set(names) != {"A", "B", "C"} or len(names) != 3:
        errors.append("history.shifts must define A, B and C exactly once")
    for shift in config.shifts:
        if shift.start == shift.end:
            errors.append(f"history.shifts.{shift.name} start and end cannot be equal")


def _validate_video(config: AppConfig, errors: list[str]) -> None:
    video = config.video
    if video.fps <= 0:
        errors.append("video.fps must be greater than zero")
    if len(video.codec) != 4:
        errors.append("video.codec must contain exactly four characters")
    _validate_resolution(video.resolution, "video.resolution", errors, allow_auto=True)
    overlay = video.overlay
    if overlay.font_scale <= 0:
        errors.append("video.overlay.font_scale must be greater than zero")
    if overlay.thickness < 1:
        errors.append("video.overlay.thickness must be greater than zero")
    if len(overlay.color) != 3 or any(not 0 <= channel <= 255 for channel in overlay.color):
        errors.append("video.overlay.color must contain three values between 0 and 255")
    if overlay.margin_bottom < 0 or overlay.margin_left < 0:
        errors.append("video.overlay margins cannot be negative")


def _validate_resolution(
    resolution: VideoResolution,
    field: str,
    errors: list[str],
    *,
    allow_auto: bool = False,
) -> None:
    dimensions = (resolution.width, resolution.height)
    if allow_auto and dimensions == (None, None):
        return
    if any(value is None or value <= 0 for value in dimensions):
        suffix = " or both must be 'auto'" if allow_auto else ""
        errors.append(f"{field} width and height must be positive integers{suffix}")


def _validate_selection(config: AppConfig, errors: list[str]) -> None:
    ids = [caster.id for caster in config.casters]
    if len(config.selected_caster_ids) != len(set(config.selected_caster_ids)):
        errors.append("selected caster ids cannot contain duplicates")
    unknown = [caster_id for caster_id in config.selected_caster_ids if caster_id not in ids]
    if unknown:
        errors.append(f"unknown caster id(s): {', '.join(unknown)}")
    inactive = [
        caster_id
        for caster_id in config.selected_caster_ids
        if caster_id in ids and not config.caster(caster_id).active
    ]
    if inactive:
        errors.append(f"inactive caster id(s) cannot be selected: {', '.join(inactive)}")
    if not config.active_casters:
        errors.append("no active casters are configured or selected")
