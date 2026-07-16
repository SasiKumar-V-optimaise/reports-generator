from datetime import date

import pytest

from reports_generator.domain.shifts import Shift
from reports_generator.shared.paths import (
    OutputPathBuilder,
    diagnosis_filename,
    overlay_video_filename,
    raw_csv_filename,
    verified_csv_filename,
    video_filename,
    workflow_metadata_filename,
)


def test_artifact_filenames_follow_the_required_convention() -> None:
    production_date = date(2026, 7, 14)

    assert raw_csv_filename(production_date, Shift.A) == "14-07-2026_shift_A.csv"
    assert verified_csv_filename(production_date, Shift.B) == "14-07-2026_shift_B_verified.csv"
    assert diagnosis_filename(production_date, Shift.C) == "14-07-2026_shift_C_diagnosis.xlsx"
    assert video_filename(production_date, Shift.C) == "14-07-2026_shift_C.mp4"
    assert (
        overlay_video_filename(production_date, Shift.C, 1024)
        == "14-07-2026_shift_C_pipe_1024_overlay.mp4"
    )
    assert (
        workflow_metadata_filename(production_date, Shift.C) == "14-07-2026_shift_C_workflow.json"
    )


def test_builder_creates_the_same_tree_for_dynamic_casters(tmp_path) -> None:
    builder = OutputPathBuilder(tmp_path / "outputs")

    created = builder.create_for_casters(("caster_1", "caster_7"))

    assert set(created) == {"caster_1", "caster_7"}
    for paths in created.values():
        assert all(path.is_dir() for path in paths.directories)
    assert builder.raw_csv_path("caster_7", date(2026, 7, 14), "a") == (
        tmp_path / "outputs/caster_7/raw_csv/14-07-2026_shift_A.csv"
    )


def test_builder_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        OutputPathBuilder(tmp_path := __import__("pathlib").Path("outputs")).for_caster("../caster")
    assert tmp_path.name == "outputs"
