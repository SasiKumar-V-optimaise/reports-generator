"""Pure pipe timing and loadcell diagnosis calculations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from .models import (
    DiagnosisStatus,
    GapStatus,
    LoadcellStatus,
    PipeDiagnosis,
    PipeRecord,
)
from .verification import classify_missing_loadcell

DEFAULT_MIN_ORIGIN_GAP = timedelta(seconds=110)
DEFAULT_MAX_ORIGIN_GAP = timedelta(seconds=190)


def format_duration(value: timedelta | float | int | None) -> str:
    """Format a duration as an absolute ``HH:MM:SS`` string."""

    if value is None:
        return ""
    seconds = value.total_seconds() if isinstance(value, timedelta) else float(value)
    total_seconds = abs(int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _validate_limits(min_gap: timedelta, max_gap: timedelta) -> None:
    if min_gap <= timedelta(0) or max_gap <= timedelta(0):
        raise ValueError("Diagnosis gap limits must be greater than zero")
    if min_gap >= max_gap:
        raise ValueError("min_gap must be less than max_gap")


def diagnose_pipe(
    pipe: PipeRecord,
    next_pipe: PipeRecord | None,
    *,
    min_gap: timedelta = DEFAULT_MIN_ORIGIN_GAP,
    max_gap: timedelta = DEFAULT_MAX_ORIGIN_GAP,
) -> PipeDiagnosis:
    """Diagnose one descending-timeline row against the following older row."""

    _validate_limits(min_gap, max_gap)
    gap = None if next_pipe is None else pipe.origin_time - next_pipe.origin_time
    if gap is None:
        gap_status = GapStatus.NO_NEXT_PIPE
    elif gap < min_gap:
        gap_status = GapStatus.TOO_FAST
    elif gap > max_gap:
        gap_status = GapStatus.TOO_SLOW
    else:
        gap_status = GapStatus.OK

    missing = classify_missing_loadcell(pipe.loadcell_enter, pipe.loadcell_exit)
    loadcell_status = missing.status
    reasons: list[str] = []
    if gap_status is GapStatus.TOO_FAST:
        reasons.append(f"T_ORIGIN_GAP_BELOW_{format_duration(min_gap)}")
    elif gap_status is GapStatus.TOO_SLOW:
        reasons.append(f"T_ORIGIN_GAP_ABOVE_{format_duration(max_gap)}")

    if loadcell_status is LoadcellStatus.MISSING_ENTRY:
        reasons.append("LOADCELL_ENTRY_MISSING")
    elif loadcell_status is LoadcellStatus.MISSING_EXIT:
        reasons.append("LOADCELL_EXIT_MISSING")
    elif loadcell_status is LoadcellStatus.MISSING_ENTRY_AND_EXIT:
        reasons.append("LOADCELL_ENTRY_AND_EXIT_MISSING")

    status = DiagnosisStatus.ABNORMAL if reasons else DiagnosisStatus.OK
    return PipeDiagnosis(
        pipe=pipe,
        next_pipe_uid=next_pipe.pipe_uid if next_pipe is not None else None,
        origin_gap=gap,
        gap_status=gap_status,
        loadcell_status=loadcell_status,
        status=status,
        reasons=tuple(reasons),
    )


def diagnose_pipes(
    pipes: Iterable[PipeRecord],
    *,
    min_gap: timedelta = DEFAULT_MIN_ORIGIN_GAP,
    max_gap: timedelta = DEFAULT_MAX_ORIGIN_GAP,
) -> tuple[PipeDiagnosis, ...]:
    """Return diagnoses in newest-to-oldest report order."""

    _validate_limits(min_gap, max_gap)
    records = tuple(
        record
        for _index, record in sorted(
            enumerate(pipes),
            key=lambda item: (item[1].origin_time, item[0]),
            reverse=True,
        )
    )
    return tuple(
        diagnose_pipe(
            record,
            records[index + 1] if index + 1 < len(records) else None,
            min_gap=min_gap,
            max_gap=max_gap,
        )
        for index, record in enumerate(records)
    )
