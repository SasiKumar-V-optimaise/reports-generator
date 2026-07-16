"""Checkpoint and G2 fallback verification."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from .models import (
    GateOpening,
    LoadcellStatus,
    MissingLoadcell,
    PipeRecord,
    VerificationDecision,
    VerificationMode,
    VerificationReason,
    VerificationResult,
    VerificationSummary,
)

DEFAULT_GATE_OPEN_MAX_INTERVAL = timedelta(seconds=120)


def classify_missing_loadcell(
    entry_time: datetime | None,
    exit_time: datetime | None,
) -> MissingLoadcell:
    """Classify which loadcell timestamps are absent."""

    return MissingLoadcell(entry_time is None, exit_time is None)


def loadcell_status(
    entry_time: datetime | None,
    exit_time: datetime | None,
) -> LoadcellStatus:
    """Convenience form of :func:`classify_missing_loadcell`."""

    return classify_missing_loadcell(entry_time, exit_time).status


def verification_window_end(
    origin_time: datetime,
    *,
    next_origin_time: datetime | None = None,
    shift_end: datetime | None = None,
    max_interval: timedelta = DEFAULT_GATE_OPEN_MAX_INTERVAL,
) -> datetime:
    """Apply the next-pipe, shift-end, and configured-duration caps."""

    if max_interval <= timedelta(0):
        raise ValueError("max_interval must be greater than zero")
    candidates = [origin_time + max_interval]
    if next_origin_time is not None:
        candidates.append(next_origin_time)
    if shift_end is not None:
        candidates.append(shift_end)
    return min(candidates)


def _gate2_times(
    openings: Iterable[GateOpening | datetime],
) -> tuple[datetime, ...]:
    values = {
        item.timestamp if isinstance(item, GateOpening) else item
        for item in openings
        if not isinstance(item, GateOpening) or item.is_gate2
    }
    return tuple(sorted(values))


def verify_pipe(
    pipe: PipeRecord,
    gate_openings: Iterable[GateOpening | datetime] = (),
    *,
    mode: VerificationMode | str = VerificationMode.LOADCELL,
    next_origin_time: datetime | None = None,
    shift_end: datetime | None = None,
    max_interval: timedelta = DEFAULT_GATE_OPEN_MAX_INTERVAL,
) -> VerificationDecision:
    """Verify one pipe using checkpoint first, then a bounded G2 window."""

    selected_mode = VerificationMode.parse(mode)
    missing = classify_missing_loadcell(pipe.loadcell_enter, pipe.loadcell_exit)
    checked = selected_mode is VerificationMode.ALL or missing.is_missing
    if not checked:
        return VerificationDecision(
            pipe=pipe,
            checked=False,
            verified=True,
            reason=VerificationReason.NOT_REQUIRED,
        )

    end = verification_window_end(
        pipe.origin_time,
        next_origin_time=next_origin_time,
        shift_end=shift_end,
        max_interval=max_interval,
    )
    if pipe.checkpoint:
        return VerificationDecision(
            pipe=pipe,
            checked=True,
            verified=True,
            reason=VerificationReason.CHECKPOINT,
            window_start=pipe.origin_time,
            window_end=end,
        )

    has_gate2 = end > pipe.origin_time and any(
        pipe.origin_time <= opening < end for opening in _gate2_times(gate_openings)
    )
    return VerificationDecision(
        pipe=pipe,
        checked=True,
        verified=has_gate2,
        reason=(VerificationReason.GATE2_OPEN if has_gate2 else VerificationReason.UNCONFIRMED),
        window_start=pipe.origin_time,
        window_end=end,
    )


def verify_pipes(
    pipes: Iterable[PipeRecord],
    gate_openings: Iterable[GateOpening | datetime] = (),
    *,
    mode: VerificationMode | str = VerificationMode.LOADCELL,
    shift_end: datetime | None = None,
    max_interval: timedelta = DEFAULT_GATE_OPEN_MAX_INTERVAL,
) -> VerificationResult:
    """Verify a batch while retaining the input record order in the result."""

    records = tuple(pipes)
    selected_mode = VerificationMode.parse(mode)
    openings = tuple(gate_openings)
    chronological = sorted(
        enumerate(records),
        key=lambda item: (item[1].origin_time, item[0]),
    )
    next_by_index: dict[int, datetime | None] = {}
    for position, (original_index, _record) in enumerate(chronological):
        next_by_index[original_index] = (
            chronological[position + 1][1].origin_time
            if position + 1 < len(chronological)
            else None
        )

    decisions = tuple(
        verify_pipe(
            record,
            openings,
            mode=selected_mode,
            next_origin_time=next_by_index[index],
            shift_end=shift_end,
            max_interval=max_interval,
        )
        for index, record in enumerate(records)
    )
    missing_count = sum(
        classify_missing_loadcell(item.loadcell_enter, item.loadcell_exit).is_missing
        for item in records
    )
    checkpoint_count = sum(item.reason is VerificationReason.CHECKPOINT for item in decisions)
    gate_count = sum(item.reason is VerificationReason.GATE2_OPEN for item in decisions)
    fallback_count = sum(item.checked and not item.pipe.checkpoint for item in decisions)
    verified_count = sum(item.verified for item in decisions)
    summary = VerificationSummary(
        mode=selected_mode,
        input_count=len(records),
        verified_count=verified_count,
        removed_count=len(records) - verified_count,
        loadcell_missing_count=missing_count,
        gate2_open_count=len(_gate2_times(openings)),
        checked_count=sum(item.checked for item in decisions),
        gate_fallback_checked_count=fallback_count,
        confirmed_by_checkpoint_count=checkpoint_count,
        confirmed_by_gate2_count=gate_count,
        unconfirmed_count=sum(item.reason is VerificationReason.UNCONFIRMED for item in decisions),
    )
    return VerificationResult(decisions=decisions, summary=summary)
