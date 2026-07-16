from datetime import datetime, timedelta

from reports_generator.domain.pipes import (
    DiagnosisStatus,
    GapStatus,
    LoadcellStatus,
    PipeRecord,
    diagnose_pipes,
)


def test_diagnosis_calculates_gaps_and_combines_reasons() -> None:
    base = datetime(2026, 7, 14, 6)
    records = (
        PipeRecord("old", base, base, base),
        PipeRecord("fast", base + timedelta(seconds=100), None, base),
        PipeRecord("slow", base + timedelta(seconds=400), base, None),
    )

    slow, fast, old = diagnose_pipes(records)

    assert slow.gap_status is GapStatus.TOO_SLOW
    assert slow.loadcell_status is LoadcellStatus.MISSING_EXIT
    assert slow.status is DiagnosisStatus.ABNORMAL
    assert slow.diagnosis_reason == "T_ORIGIN_GAP_ABOVE_00:03:10; LOADCELL_EXIT_MISSING"
    assert fast.gap_status is GapStatus.TOO_FAST
    assert fast.highlight_color == "red"
    assert old.gap_status is GapStatus.NO_NEXT_PIPE
    assert old.status is DiagnosisStatus.OK


def test_gap_boundaries_are_inclusive_ok() -> None:
    base = datetime(2026, 7, 14, 6)
    records = (PipeRecord("new", base + timedelta(seconds=110)), PipeRecord("old", base))
    assert diagnose_pipes(records)[0].gap_status is GapStatus.OK
