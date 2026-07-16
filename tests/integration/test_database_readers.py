from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reports_generator.infrastructure.database import (
    SQLiteConnectionFactory,
    SQLiteGateReader,
    SQLitePipeReader,
)

PIPE_SCHEMA = """
CREATE TABLE pipes (
    pipe_uid INTEGER,
    origin TEXT,
    t_origin REAL,
    t_loadcell_enter REAL,
    t_loadcell_exit REAL,
    weight REAL,
    weight_quality TEXT,
    weight_samples INTEGER,
    state TEXT,
    last_seen_ts REAL
)
"""


def test_pipe_reader_projects_required_columns_and_legacy_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "pipes.db"
    with sqlite3.connect(database) as connection:
        connection.execute(PIPE_SCHEMA)
        connection.executemany(
            "INSERT INTO pipes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (10, "left", 0, None, 60, 100.5, "good", 8, "done", 120),
                (11, "right", 1, 2, 3, 101.5, "good", 9, "done", 121),
            ],
        )

    records = SQLitePipeReader(SQLiteConnectionFactory(database)).read(0, 1)

    assert [record.pipe_uid for record in records] == [11, 10]
    assert records[0].pipe_checkpoint == 0
    assert records[0].t_origin == "1970-01-01 05:30:01"
    assert records[1].t_loadcell_enter is None
    assert tuple(records[0].as_dict()) == SQLitePipeReader.columns


def test_pipe_reader_uses_checkpoint_when_column_exists(tmp_path: Path) -> None:
    database = tmp_path / "pipes-new.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            PIPE_SCHEMA.replace("t_origin REAL,", "pipe_checkpoint INTEGER, t_origin REAL,")
        )
        connection.execute(
            "INSERT INTO pipes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (20, "left", 1, 10, 11, 12, 99, "ok", 3, "done", 13),
        )

    record = SQLitePipeReader(database).read(10, 10)[0]
    assert record.pipe_checkpoint == 1


def test_gate_reader_falls_back_to_first_non_empty_supported_table(tmp_path: Path) -> None:
    database = tmp_path / "gates.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE gate_openings (id INTEGER, gate_name TEXT, t_open REAL)")
        connection.execute(
            "CREATE TABLE gate_open_events (id INTEGER, gate_name TEXT, t_open REAL)"
        )
        connection.execute(
            "CREATE TABLE gate_cycles (id INTEGER, t_gate1_open REAL, t_gate2_open REAL)"
        )
        connection.execute("INSERT INTO gate_open_events VALUES (2, 'gate2', 10)")
        connection.execute("INSERT INTO gate_cycles VALUES (3, 11, 12)")

    reader = SQLiteGateReader(database)
    result = reader.read(0, 20)

    assert result.source_table == "gate_open_events"
    assert len(result) == 1
    assert result[0].as_dict() == {
        "id": 2,
        "gate_name": "gate2",
        "t_open_IST": "1970-01-01 05:30:10",
    }

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM gate_open_events")

    fallback = reader.read(0, 20)
    assert fallback.source_table == "gate_cycles"
    assert [(row.id, row.gate_name) for row in fallback] == [(3, "gate1"), (3, "gate2")]


def test_readers_reject_reversed_ranges(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    database.touch()
    with pytest.raises(ValueError, match="end_timestamp"):
        SQLitePipeReader(database).read(2, 1)
    with pytest.raises(ValueError, match="end_timestamp"):
        SQLiteGateReader(database).read(2, 1)
