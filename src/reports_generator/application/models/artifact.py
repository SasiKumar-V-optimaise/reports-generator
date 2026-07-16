"""Typed workflow artifact models."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ArtifactType(str, Enum):
    RAW_CSV = "raw_csv"
    VERIFIED_CSV = "verified_csv"
    DIAGNOSIS = "diagnosis"
    VIDEO = "video"
    FULL_SHIFT_VIDEO = "video"
    OVERLAY_VIDEO = "overlay_video"
    METADATA = "workflow_metadata"


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_type: ArtifactType
    caster_id: str
    path: Path


@dataclass(frozen=True, slots=True)
class StageResult:
    stage: str
    success: bool
    artifacts: tuple[Artifact, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
