"""Immutable values used by pipe business rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class LoadcellStatus(str, Enum):
    OK = "OK"
    MISSING_ENTRY = "MISSING_ENTRY"
    MISSING_EXIT = "MISSING_EXIT"
    MISSING_ENTRY_AND_EXIT = "MISSING_ENTRY_AND_EXIT"


@dataclass(frozen=True)
class MissingLoadcell:
    missing_entry: bool
    missing_exit: bool

    @property
    def is_missing(self) -> bool:
        return self.missing_entry or self.missing_exit

    @property
    def status(self) -> LoadcellStatus:
        if self.missing_entry and self.missing_exit:
            return LoadcellStatus.MISSING_ENTRY_AND_EXIT
        if self.missing_entry:
            return LoadcellStatus.MISSING_ENTRY
        if self.missing_exit:
            return LoadcellStatus.MISSING_EXIT
        return LoadcellStatus.OK


@dataclass(frozen=True)
class PipeRecord:
    """Infrastructure-neutral pipe data required by domain rules."""

    pipe_uid: str
    origin_time: datetime
    loadcell_enter: datetime | None = None
    loadcell_exit: datetime | None = None
    checkpoint: bool = False

    @property
    def t_origin(self) -> datetime:
        return self.origin_time

    @property
    def t_loadcell_enter(self) -> datetime | None:
        return self.loadcell_enter

    @property
    def t_loadcell_exit(self) -> datetime | None:
        return self.loadcell_exit


@dataclass(frozen=True)
class GateOpening:
    timestamp: datetime
    gate_name: str = "gate2"

    @property
    def is_gate2(self) -> bool:
        compact = "".join(
            character for character in self.gate_name.strip().lower() if character not in " _-"
        )
        return compact in {"2", "g2", "gate2"} or compact.endswith("gate2")


class VerificationMode(str, Enum):
    LOADCELL = "loadcell"
    ALL = "all"

    @classmethod
    def parse(cls, value: VerificationMode | str) -> VerificationMode:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError("Verification mode must be 'loadcell' or 'all'") from exc


class VerificationReason(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CHECKPOINT = "CHECKPOINT"
    GATE2_OPEN = "GATE2_OPEN"
    UNCONFIRMED = "UNCONFIRMED"


@dataclass(frozen=True)
class VerificationDecision:
    pipe: PipeRecord
    checked: bool
    verified: bool
    reason: VerificationReason
    window_start: datetime | None = None
    window_end: datetime | None = None

    @property
    def keep(self) -> bool:
        return self.verified


@dataclass(frozen=True)
class VerificationSummary:
    mode: VerificationMode
    input_count: int
    verified_count: int
    removed_count: int
    loadcell_missing_count: int
    gate2_open_count: int
    checked_count: int
    gate_fallback_checked_count: int
    confirmed_by_checkpoint_count: int
    confirmed_by_gate2_count: int
    unconfirmed_count: int


@dataclass(frozen=True)
class VerificationResult:
    decisions: tuple[VerificationDecision, ...]
    summary: VerificationSummary

    @property
    def verified_records(self) -> tuple[PipeRecord, ...]:
        return tuple(item.pipe for item in self.decisions if item.verified)

    @property
    def removed_records(self) -> tuple[PipeRecord, ...]:
        return tuple(item.pipe for item in self.decisions if not item.verified)


class GapStatus(str, Enum):
    OK = "OK"
    NO_NEXT_PIPE = "NO_NEXT_PIPE"
    TOO_FAST = "TOO_FAST"
    TOO_SLOW = "TOO_SLOW"


class DiagnosisStatus(str, Enum):
    OK = "OK"
    ABNORMAL = "ABNORMAL"


@dataclass(frozen=True)
class PipeDiagnosis:
    pipe: PipeRecord
    next_pipe_uid: str | None
    origin_gap: timedelta | None
    gap_status: GapStatus
    loadcell_status: LoadcellStatus
    status: DiagnosisStatus
    reasons: tuple[str, ...] = ()

    @property
    def diagnosis_reason(self) -> str:
        return "; ".join(self.reasons)

    @property
    def highlight_color(self) -> str:
        return "red" if self.status is DiagnosisStatus.ABNORMAL else ""
