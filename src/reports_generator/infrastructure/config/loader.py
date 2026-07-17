"""Load, merge and type application configuration exactly once."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import time, timedelta
from functools import cache
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from .models import (
    AppConfig,
    CasterConfig,
    DiagnosisConfig,
    EmailConfig,
    GateCoverageConfig,
    LoggingConfig,
    MissingLoadcellVideoConfig,
    PathsConfig,
    ShiftConfig,
    StorageConfig,
    UploadConfig,
    VerificationConfig,
    VideoConfig,
    VideoOverlayConfig,
    VideoResolution,
    VideoRetentionConfig,
)
from .validator import ConfigValidationError, validate_config, validate_selection

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ConfigLoader:
    """Read the runtime and video YAML files once, then serve typed selections.

    The cached base configuration always contains every configured caster.  A
    caller-specific caster selection is a cheap immutable view and never causes
    either YAML file to be read again.
    """

    def __init__(
        self,
        project_root: Path,
        runtime_path: Path | None = None,
        video_path: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.runtime_path = self._configuration_path(runtime_path, "config/runtime.yaml")
        self.video_path = self._configuration_path(video_path, "config/video.yaml")
        self._base_config: AppConfig | None = None
        self._lock = Lock()

    def load(self, selected_caster_ids: Iterable[str] = ()) -> AppConfig:
        base = self._load_base()
        selected = tuple(str(value).strip() for value in selected_caster_ids)
        validate_selection(base, selected)
        return replace(base, selected_caster_ids=selected)

    def _load_base(self) -> AppConfig:
        if self._base_config is not None:
            return self._base_config
        with self._lock:
            if self._base_config is None:
                runtime = _read_yaml(self.runtime_path)
                video = _read_yaml(self.video_path)
                combined = _deep_merge(runtime, video)
                parsed = _parse_config(combined, self.project_root)
                validate_config(parsed)
                self._base_config = parsed
        return self._base_config

    def _configuration_path(self, value: Path | None, default: str) -> Path:
        path = Path(value) if value is not None else Path(default)
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()


@cache
def _cached_loader(
    project_root: Path, runtime_path: Path | None, video_path: Path | None
) -> ConfigLoader:
    return ConfigLoader(project_root, runtime_path, video_path)


def load_config(
    project_root: Path = DEFAULT_PROJECT_ROOT,
    runtime_path: Path | None = None,
    video_path: Path | None = None,
    selected_caster_ids: Iterable[str] = (),
) -> AppConfig:
    """Return the process-wide typed configuration.

    This convenience function shares a ``ConfigLoader`` for identical path
    arguments.  Tests that need isolation can instantiate ``ConfigLoader``
    directly or call :func:`clear_config_cache`.
    """

    root = Path(project_root).expanduser().resolve()
    runtime = Path(runtime_path) if runtime_path is not None else None
    video = Path(video_path) if video_path is not None else None
    return _cached_loader(root, runtime, video).load(selected_caster_ids)


def clear_config_cache() -> None:
    """Forget process-wide loaders (intended for tests and controlled reloads)."""

    _cached_loader.cache_clear()


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except FileNotFoundError as exc:
        raise ConfigValidationError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigValidationError(f"Invalid YAML in {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigValidationError(f"Configuration root must be a mapping: {path}")
    return value


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _parse_config(data: Mapping[str, Any], project_root: Path) -> AppConfig:
    paths = _parse_paths(_section(data, "paths"), project_root)
    casters = _parse_casters(data.get("casters"), data, project_root)
    history = _section(data, "history")
    shifts = _parse_shifts(history.get("shifts"))
    video = _parse_video(_section(data, "video"))
    diagnosis = _parse_diagnosis(_section(data, "diagnosis"))
    verification = _parse_verification(data)
    missing_video = _parse_missing_loadcell_video(_section(data, "missing_loadcell_video"))
    gate = _parse_gate_coverage(data)
    email = _parse_email(_section(data, "email"))
    upload = _parse_upload(data)
    retention = _parse_retention(_section(data, "video_retention"))
    storage = _parse_storage(data, project_root)
    logging = _parse_logging(_section(data, "logging"))
    return AppConfig(
        project_root=project_root,
        paths=paths,
        casters=casters,
        shifts=shifts,
        video=video,
        diagnosis=diagnosis,
        verification=verification,
        missing_loadcell_video=missing_video,
        gate_coverage=gate,
        email=email,
        upload=upload,
        video_retention=retention,
        storage=storage,
        logging=logging,
    )


def _parse_paths(value: Mapping[str, Any], root: Path) -> PathsConfig:
    return PathsConfig(
        output_root=_resolve_path(value.get("output_root", "outputs"), root, "paths.output_root"),
        state_root=_resolve_path(
            value.get("state_root", "runtime/state"), root, "paths.state_root"
        ),
        temp_root=_resolve_path(value.get("temp_root", "runtime/temp"), root, "paths.temp_root"),
        log_root=_resolve_path(value.get("log_root", "logs"), root, "paths.log_root"),
    )


def _parse_casters(value: Any, data: Mapping[str, Any], root: Path) -> tuple[CasterConfig, ...]:
    if isinstance(value, list):
        return tuple(
            _parse_caster_item(_mapping(item, f"casters[{index}]"), {}, data, root, index)
            for index, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        defaults = _section(value, "defaults")
        items = value.get("items")
        if not isinstance(items, list):
            raise ConfigValidationError("casters.items must be a list")
        return tuple(
            _parse_caster_item(
                _mapping(item, f"casters.items[{index}]"), defaults, data, root, index
            )
            for index, item in enumerate(items)
        )
    raise ConfigValidationError("casters must be a list")


def _parse_caster_item(
    item: Mapping[str, Any],
    defaults: Mapping[str, Any],
    data: Mapping[str, Any],
    root: Path,
    index: int,
) -> CasterConfig:
    field = f"casters[{index}]"
    caster_id = _required_text(item.get("id"), f"{field}.id")
    number = item.get("number")
    context = {
        "caster_id": caster_id,
        "id": caster_id,
        "number": number if number is not None else "",
        "caster_number": number if number is not None else "",
    }
    display_name = str(
        item.get("display_name")
        or item.get("name")
        or (f"Caster {number}" if number not in (None, "") else caster_id)
    ).strip()
    active_value = item.get(
        "active",
        item.get("enabled", defaults.get("active", defaults.get("enabled", True))),
    )

    var_dir_value = item.get("var_dir")
    if var_dir_value is None and defaults.get("var_root") is not None:
        var_dir_value = str(Path(str(defaults["var_root"])) / caster_id)

    explicit_database_path = _nested_value(item, "database", "path")
    database_directory_value = item.get("database_directory")
    database_file_value = item.get("database_file") or defaults.get("database_file")
    if explicit_database_path is not None:
        db_path = Path(_format_value(explicit_database_path, context))
        database_directory_value = database_directory_value or str(db_path.parent)
        database_file_value = database_file_value or db_path.name
    if database_directory_value is None:
        database_directory_value = var_dir_value
    if database_file_value is None:
        database_file_value = "pipes.db"

    history_directory_value = item.get("history_directory") or _nested_value(
        item, "history", "image_root"
    )
    if history_directory_value is None and var_dir_value is not None:
        history_directory_value = str(
            Path(str(var_dir_value)) / str(defaults.get("history_dir", "history"))
        )
    recording_directory_value = (
        item.get("recording_directory")
        or _nested_value(item, "recording", "directory")
        or history_directory_value
    )
    roi_path_value = (
        item.get("roi_path")
        or _nested_value(item, "rois", "path")
        or _nested_value(defaults, "rois", "path")
        or _nested_value(data, "rois", "path")
    )

    return CasterConfig(
        id=caster_id,
        display_name=display_name,
        active=_as_bool(active_value, f"{field}.active"),
        database_directory=_resolve_path(
            database_directory_value, root, f"{field}.database_directory"
        ),
        database_file=_format_value(database_file_value, context),
        history_directory=_resolve_path(
            history_directory_value, root, f"{field}.history_directory"
        ),
        recording_directory=_resolve_path(
            recording_directory_value, root, f"{field}.recording_directory"
        ),
        roi_path=_resolve_path(roi_path_value, root, f"{field}.roi_path"),
        number=number,
    )


def _parse_shifts(value: Any) -> tuple[ShiftConfig, ...]:
    if not isinstance(value, list):
        raise ConfigValidationError("history.shifts must be a list")
    shifts: list[ShiftConfig] = []
    for index, raw in enumerate(value):
        item = _mapping(raw, f"history.shifts[{index}]")
        shifts.append(
            ShiftConfig(
                name=_shift_name(item.get("name"), f"history.shifts[{index}].name"),
                start=_parse_time(item.get("start"), f"history.shifts[{index}].start"),
                end=_parse_time(item.get("end"), f"history.shifts[{index}].end"),
            )
        )
    return tuple(shifts)


def _parse_video(value: Mapping[str, Any]) -> VideoConfig:
    resolution = _section(value, "output_resolution") or _section(value, "resolution")
    overlay = _section(value, "overlay")
    color_value = overlay.get("color", (0, 255, 255))
    if not isinstance(color_value, Sequence) or isinstance(color_value, (str, bytes)):
        raise ConfigValidationError("video.overlay.color must be a three-item sequence")
    return VideoConfig(
        resolution=VideoResolution(
            width=_dimension(resolution.get("width", "auto"), "video.resolution.width"),
            height=_dimension(resolution.get("height", "auto"), "video.resolution.height"),
        ),
        fps=_as_float(value.get("fps", 5), "video.fps"),
        codec=_required_text(value.get("codec", "mp4v"), "video.codec"),
        input_images_have_overlay=_as_bool(
            value.get("input_images_have_overlay", False),
            "video.input_images_have_overlay",
        ),
        overlay=VideoOverlayConfig(
            font_scale=_as_float(overlay.get("font_scale", 0.7), "video.overlay.font_scale"),
            thickness=_as_int(overlay.get("thickness", 2), "video.overlay.thickness"),
            color=tuple(_as_int(channel, "video.overlay.color") for channel in color_value),
            margin_bottom=_as_int(overlay.get("margin_bottom", 20), "video.overlay.margin_bottom"),
            margin_left=_as_int(overlay.get("margin_left", 20), "video.overlay.margin_left"),
        ),
    )


def _parse_diagnosis(value: Mapping[str, Any]) -> DiagnosisConfig:
    return DiagnosisConfig(
        t_origin_gap_min=_duration(value.get("t_origin_gap_min", 90), "diagnosis.t_origin_gap_min"),
        t_origin_gap_max=_duration(
            value.get("t_origin_gap_max", 200), "diagnosis.t_origin_gap_max"
        ),
    )


def _parse_verification(data: Mapping[str, Any]) -> VerificationConfig:
    section = _section(data, "verification")
    mode = section.get("mode", data.get("verified_pipes_mode", "loadcell"))
    seconds = section.get(
        "gate_open_max_interval_seconds",
        section.get(
            "gate_open_max_interval",
            data.get("verified_pipes_gate_open_max_interval_seconds", 120),
        ),
    )
    return VerificationConfig(
        mode=_required_text(mode, "verification.mode").lower(),
        gate_open_max_interval=_duration(seconds, "verification.gate_open_max_interval"),
    )


def _parse_missing_loadcell_video(value: Mapping[str, Any]) -> MissingLoadcellVideoConfig:
    return MissingLoadcellVideoConfig(
        enabled=_as_bool(value.get("enabled", True), "missing_loadcell_video.enabled"),
        pre_origin=_duration(
            value.get("pre_origin_seconds", value.get("pre_origin", 60)),
            "missing_loadcell_video.pre_origin",
        ),
        clip_duration=_duration(
            value.get("clip_duration_seconds", value.get("clip_duration", 300)),
            "missing_loadcell_video.clip_duration",
        ),
        delete_after_upload=_as_bool(
            value.get("delete_after_upload", True),
            "missing_loadcell_video.delete_after_upload",
        ),
    )


def _parse_gate_coverage(data: Mapping[str, Any]) -> GateCoverageConfig:
    value = _section(data, "gate_coverage") or _section(data, "gate2_closed_position_report")
    resolution = _section(value, "source_resolution")
    return GateCoverageConfig(
        interval=_duration(
            value.get("interval_seconds", _minutes(value.get("interval_minutes", 10))),
            "gate_coverage.interval",
        ),
        recent_window=_duration(
            value.get("recent_window_seconds", _minutes(value.get("recent_window_minutes", 10))),
            "gate_coverage.recent_window",
        ),
        minimum_average_percent=_as_float(
            value.get(
                "minimum_average_percent",
                value.get("min_average_percent", value.get("min_avg_coverage_percent", 80)),
            ),
            "gate_coverage.minimum_average_percent",
        ),
        roi_name=_required_text(
            value.get("roi_name", "roi_gate2_closed"), "gate_coverage.roi_name"
        ),
        gate_class_id=_as_int(
            value.get("gate_class_id", value.get("gate2_class_id", 3)),
            "gate_coverage.gate_class_id",
        ),
        source_resolution=VideoResolution(
            width=_dimension(
                resolution.get("width", 1310), "gate_coverage.source_resolution.width"
            ),
            height=_dimension(
                resolution.get("height", 608), "gate_coverage.source_resolution.height"
            ),
        ),
        alert_on_no_samples=_as_bool(
            value.get("alert_on_no_samples", False), "gate_coverage.alert_on_no_samples"
        ),
        send_email=_as_bool(value.get("send_email", True), "gate_coverage.send_email"),
    )


def _parse_email(value: Mapping[str, Any]) -> EmailConfig:
    return EmailConfig(
        smtp_host=_required_text(
            value.get("smtp_host", value.get("smtp_server")), "email.smtp_host"
        ),
        smtp_port=_as_int(value.get("smtp_port", 587), "email.smtp_port"),
        sender=_required_text(value.get("sender"), "email.sender"),
        password_env=_required_text(
            value.get("password_env", "EMAIL_APP_PASSWORD"), "email.password_env"
        ),
        recipients=_string_tuple(value.get("recipients", ()), "email.recipients"),
        enabled=_as_bool(value.get("enabled", True), "email.enabled"),
        test_recipients=_string_tuple(value.get("test_recipients", ()), "email.test_recipients"),
        diagnosis_recipients=_string_tuple(
            value.get("diagnosis_recipients", ()),
            "email.diagnosis_recipients",
        ),
        verified_recipients=_string_tuple(
            value.get("verified_recipients", ()),
            "email.verified_recipients",
        ),
        send_csv_attachment=_as_bool(
            value.get("send_csv_attachment", True), "email.send_csv_attachment"
        ),
        use_starttls=_as_bool(value.get("use_starttls", True), "email.use_starttls"),
        timeout_seconds=_as_float(value.get("timeout_seconds", 30), "email.timeout_seconds"),
    )


def _parse_upload(data: Mapping[str, Any]) -> UploadConfig:
    value = _section(data, "upload") or _section(data, "gdrive")
    return UploadConfig(
        remote=_required_text(value.get("remote", "gdrive"), "upload.remote"),
        base_path=_required_text(value.get("base_path", "reports"), "upload.base_path").strip("/"),
        csv_directory=_required_text(
            value.get(
                "raw_csv_directory",
                value.get("csv_directory", value.get("pipes_csv_dir", "Pipes_Data_Sheet")),
            ),
            "upload.csv_directory",
        ).strip("/"),
        videos_directory=_required_text(
            value.get(
                "video_directory", value.get("videos_directory", value.get("videos_dir", "videos"))
            ),
            "upload.videos_directory",
        ).strip("/"),
        chunk_size=_required_text(value.get("chunk_size", "128M"), "upload.chunk_size"),
        enabled=_as_bool(value.get("enabled", True), "upload.enabled"),
    )


def _parse_retention(value: Mapping[str, Any]) -> VideoRetentionConfig:
    return VideoRetentionConfig(
        keep_days=_as_int(value.get("keep_days", 5), "video_retention.keep_days"),
        include_overlay_videos=_as_bool(
            value.get("include_overlay_videos", True),
            "video_retention.include_overlay_videos",
        ),
    )


def _parse_storage(data: Mapping[str, Any], root: Path) -> StorageConfig:
    value = _section(data, "storage") or _section(data, "jetson_storage_alert")
    path_value = value.get("path")
    return StorageConfig(
        threshold_percent=_as_int(
            value.get("alert_threshold_percent", value.get("threshold_percent", 90)),
            "storage.threshold_percent",
        ),
        recipient_mode=_required_text(
            value.get("recipient_mode", "test"), "storage.recipient_mode"
        ).lower(),
        device=str(value["device"]).strip() if value.get("device") else None,
        path=_resolve_path(path_value, root, "storage.path") if path_value is not None else None,
    )


def _parse_logging(value: Mapping[str, Any]) -> LoggingConfig:
    return LoggingConfig(
        level=_required_text(value.get("level", "INFO"), "logging.level").upper(),
        max_bytes=_as_int(value.get("max_bytes", 10 * 1024 * 1024), "logging.max_bytes"),
        backup_count=_as_int(value.get("backup_count", 10), "logging.backup_count"),
    )


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigValidationError(f"{key} must be a mapping")
    return value


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigValidationError(f"{field} must be a mapping")
    return value


def _nested_value(data: Mapping[str, Any], section: str, key: str) -> Any:
    nested = data.get(section)
    return nested.get(key) if isinstance(nested, Mapping) else None


def _resolve_path(value: Any, root: Path, field: str) -> Path:
    text = _required_text(value, field)
    if "\x00" in text:
        raise ConfigValidationError(f"{field} contains a null byte")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def _required_text(value: Any, field: str) -> str:
    if value is None or not str(value).strip():
        raise ConfigValidationError(f"{field} is required and cannot be blank")
    return str(value).strip()


def _format_value(value: Any, context: Mapping[str, Any]) -> str:
    text = str(value)
    try:
        return text.format(**context)
    except (KeyError, ValueError) as exc:
        raise ConfigValidationError(f"Invalid caster path template {text!r}: {exc}") from exc


def _as_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ConfigValidationError(f"{field} must be a boolean")


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ConfigValidationError(f"{field} must be an integer")
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"{field} must be an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ConfigValidationError(f"{field} must be an integer")
    return converted


def _as_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ConfigValidationError(f"{field} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"{field} must be numeric") from exc


def _dimension(value: Any, field: str) -> int | None:
    if value is None or (isinstance(value, str) and value.strip().lower() == "auto"):
        return None
    return _as_int(value, field)


def _parse_time(value: Any, field: str) -> time:
    text = _required_text(value, field)
    parts = text.split(":")
    if len(parts) not in {2, 3}:
        raise ConfigValidationError(f"{field} must use HH:MM or HH:MM:SS")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return time(hour, minute, second)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"{field} is not a valid time: {text!r}") from exc


def _shift_name(value: Any, field: str) -> str:
    text = _required_text(value, field).upper()
    if text.startswith("SHIFT_"):
        text = text.split("_", 1)[1]
    return text


def _duration(value: Any, field: str) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return timedelta(seconds=float(value))
    text = _required_text(value, field)
    try:
        if ":" not in text:
            return timedelta(seconds=float(text))
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
        if minutes not in range(60) or not 0 <= seconds < 60:
            raise ValueError
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except ValueError as exc:
        raise ConfigValidationError(f"{field} must be seconds or HH:MM:SS") from exc


def _minutes(value: Any) -> float:
    return _as_float(value, "minutes") * 60


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    items: Sequence[Any]
    if isinstance(value, str):
        items = (value,)
    elif isinstance(value, Sequence):
        items = value
    else:
        raise ConfigValidationError(f"{field} must be a string or list of strings")
    result = tuple(str(item).strip() for item in items)
    if any(not item for item in result):
        raise ConfigValidationError(f"{field} cannot contain blank addresses")
    return result
