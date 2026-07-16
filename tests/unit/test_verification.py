from datetime import datetime, timedelta

from reports_generator.domain.pipes import (
    GateOpening,
    LoadcellStatus,
    PipeRecord,
    VerificationReason,
    classify_missing_loadcell,
    verify_pipes,
)


def _pipe(uid: str, minute: int, *, complete: bool = False, checkpoint: bool = False) -> PipeRecord:
    origin = datetime(2026, 6, 26, 22, minute)
    return PipeRecord(
        uid,
        origin,
        origin + timedelta(seconds=10) if complete else None,
        origin + timedelta(seconds=20) if complete else None,
        checkpoint,
    )


def test_missing_loadcell_classification() -> None:
    assert classify_missing_loadcell(None, None).status is LoadcellStatus.MISSING_ENTRY_AND_EXIT
    now = datetime(2026, 1, 1)
    assert classify_missing_loadcell(None, now).status is LoadcellStatus.MISSING_ENTRY
    assert classify_missing_loadcell(now, None).status is LoadcellStatus.MISSING_EXIT
    assert classify_missing_loadcell(now, now).status is LoadcellStatus.OK


def test_checkpoint_then_gate2_fallback_and_unchecked_complete_pipe() -> None:
    records = (
        _pipe("checkpoint", 0, checkpoint=True),
        _pipe("gate", 2),
        _pipe("complete", 4, complete=True),
        _pipe("fail", 6),
    )
    result = verify_pipes(
        records,
        (GateOpening(datetime(2026, 6, 26, 22, 3), "g2"),),
        shift_end=datetime(2026, 6, 27, 6),
    )

    assert [item.pipe_uid for item in result.verified_records] == ["checkpoint", "gate", "complete"]
    assert [item.reason for item in result.decisions] == [
        VerificationReason.CHECKPOINT,
        VerificationReason.GATE2_OPEN,
        VerificationReason.NOT_REQUIRED,
        VerificationReason.UNCONFIRMED,
    ]
    assert result.summary.confirmed_by_gate2_count == 1


def test_gate_at_window_end_does_not_confirm() -> None:
    record = _pipe("boundary", 0)
    result = verify_pipes((record,), (record.origin_time + timedelta(seconds=120),))
    assert not result.decisions[0].verified
