"""The single source of truth for caster artifact paths and filenames."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from reports_generator.domain.shifts.models import Shift
from reports_generator.shared.time import format_output_date

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ArtifactKind(str, Enum):
    RAW_CSV = "raw_csv"
    VERIFIED_CSV = "verified_csv"
    DIAGNOSIS = "diagnosis"
    VIDEO = "video"
    OVERLAY_VIDEO = "overlay_video"
    WORKFLOW_METADATA = "workflow_metadata"


@dataclass(frozen=True)
class CasterOutputPaths:
    root: Path
    raw_csv: Path
    verified_csv: Path
    diagnosis: Path
    videos: Path
    overlay_videos: Path
    metadata: Path

    @property
    def directories(self) -> tuple[Path, ...]:
        """Directories in parent-before-child creation order."""

        return (
            self.root,
            self.raw_csv,
            self.verified_csv,
            self.diagnosis,
            self.videos,
            self.overlay_videos,
            self.metadata,
        )


def _safe_component(value: object, *, name: str) -> str:
    token = str(value)
    if not token or token != token.strip() or not _SAFE_COMPONENT.fullmatch(token):
        raise ValueError(f"{name} must be a non-empty filename-safe identifier")
    if token in {".", ".."}:
        raise ValueError(f"{name} cannot be {token!r}")
    return token


def build_shift_filename(
    production_date: date,
    shift: Shift | str,
    suffix: str,
    extension: str,
) -> str:
    """Build a filename following ``DD-MM-YYYY_shift_X`` conventions."""

    shift_value = Shift.parse(shift)
    normalized_extension = extension.removeprefix(".")
    if not normalized_extension or not normalized_extension.isalnum():
        raise ValueError("extension must contain only letters and numbers")
    if suffix and (not suffix.startswith("_") or any(c in suffix for c in "/\\")):
        raise ValueError("suffix must be empty or start with '_' and contain no path separator")
    return (
        f"{format_output_date(production_date)}_shift_{shift_value.value}"
        f"{suffix}.{normalized_extension}"
    )


def raw_csv_filename(production_date: date, shift: Shift | str) -> str:
    return build_shift_filename(production_date, shift, "", "csv")


def verified_csv_filename(production_date: date, shift: Shift | str) -> str:
    return build_shift_filename(production_date, shift, "_verified", "csv")


def diagnosis_filename(production_date: date, shift: Shift | str) -> str:
    return build_shift_filename(production_date, shift, "_diagnosis", "xlsx")


def video_filename(production_date: date, shift: Shift | str) -> str:
    return build_shift_filename(production_date, shift, "", "mp4")


full_shift_video_filename = video_filename


def overlay_video_filename(
    production_date: date,
    shift: Shift | str,
    pipe_id: str | int,
) -> str:
    pipe_token = _safe_component(pipe_id, name="pipe_id")
    return build_shift_filename(
        production_date,
        shift,
        f"_pipe_{pipe_token}_overlay",
        "mp4",
    )


def workflow_metadata_filename(production_date: date, shift: Shift | str) -> str:
    return build_shift_filename(production_date, shift, "_workflow", "json")


workflow_filename = workflow_metadata_filename


class OutputPathBuilder:
    """Build and centrally create all configured caster output paths."""

    def __init__(self, output_root: Path) -> None:
        self._output_root = Path(output_root)

    @property
    def output_root(self) -> Path:
        return self._output_root

    def for_caster(self, caster_id: str) -> CasterOutputPaths:
        caster_token = _safe_component(caster_id, name="caster_id")
        root = self._output_root / caster_token
        return CasterOutputPaths(
            root=root,
            raw_csv=root / "raw_csv",
            verified_csv=root / "verified_csv",
            diagnosis=root / "diagnosis",
            videos=root / "videos",
            overlay_videos=root / "overlay_videos",
            metadata=root / "metadata",
        )

    def create_for_caster(self, caster_id: str) -> CasterOutputPaths:
        """Create the complete, consistent tree for one caster."""

        paths = self.for_caster(caster_id)
        for directory in paths.directories:
            directory.mkdir(parents=True, exist_ok=True)
        return paths

    # ``ensure`` communicates idempotence at bootstrap call sites.
    ensure_for_caster = create_for_caster

    def create_for_casters(
        self,
        caster_ids: Iterable[str],
    ) -> dict[str, CasterOutputPaths]:
        """Create trees for configured casters without hard-coded IDs."""

        created: dict[str, CasterOutputPaths] = {}
        for caster_id in caster_ids:
            if caster_id in created:
                continue
            created[caster_id] = self.create_for_caster(caster_id)
        return created

    ensure_for_casters = create_for_casters

    def raw_csv_path(self, caster_id: str, production_date: date, shift: Shift | str) -> Path:
        return self.for_caster(caster_id).raw_csv / raw_csv_filename(production_date, shift)

    def verified_csv_path(self, caster_id: str, production_date: date, shift: Shift | str) -> Path:
        return self.for_caster(caster_id).verified_csv / verified_csv_filename(
            production_date, shift
        )

    def diagnosis_path(self, caster_id: str, production_date: date, shift: Shift | str) -> Path:
        return self.for_caster(caster_id).diagnosis / diagnosis_filename(production_date, shift)

    def video_path(self, caster_id: str, production_date: date, shift: Shift | str) -> Path:
        return self.for_caster(caster_id).videos / video_filename(production_date, shift)

    full_shift_video_path = video_path

    def overlay_video_path(
        self,
        caster_id: str,
        production_date: date,
        shift: Shift | str,
        pipe_id: str | int,
    ) -> Path:
        return self.for_caster(caster_id).overlay_videos / overlay_video_filename(
            production_date, shift, pipe_id
        )

    def workflow_metadata_path(
        self, caster_id: str, production_date: date, shift: Shift | str
    ) -> Path:
        return self.for_caster(caster_id).metadata / workflow_metadata_filename(
            production_date, shift
        )

    workflow_path = workflow_metadata_path

    def artifact_path(
        self,
        caster_id: str,
        production_date: date,
        shift: Shift | str,
        kind: ArtifactKind,
        *,
        pipe_id: str | int | None = None,
    ) -> Path:
        """Resolve any final artifact without callers joining path fragments."""

        if kind is ArtifactKind.RAW_CSV:
            return self.raw_csv_path(caster_id, production_date, shift)
        if kind is ArtifactKind.VERIFIED_CSV:
            return self.verified_csv_path(caster_id, production_date, shift)
        if kind is ArtifactKind.DIAGNOSIS:
            return self.diagnosis_path(caster_id, production_date, shift)
        if kind is ArtifactKind.VIDEO:
            return self.video_path(caster_id, production_date, shift)
        if kind is ArtifactKind.OVERLAY_VIDEO:
            if pipe_id is None:
                raise ValueError("pipe_id is required for an overlay video")
            return self.overlay_video_path(caster_id, production_date, shift, pipe_id)
        if kind is ArtifactKind.WORKFLOW_METADATA:
            return self.workflow_metadata_path(caster_id, production_date, shift)
        raise ValueError(f"Unsupported artifact kind: {kind!r}")


__all__ = [
    "ArtifactKind",
    "CasterOutputPaths",
    "OutputPathBuilder",
    "build_shift_filename",
    "diagnosis_filename",
    "format_output_date",
    "full_shift_video_filename",
    "overlay_video_filename",
    "raw_csv_filename",
    "verified_csv_filename",
    "video_filename",
    "workflow_metadata_filename",
]
