"""Read gate opening events across supported SQLite schema generations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, overload

from .connection import SQLiteConnectionFactory

GateSourceTable = Literal["gate_openings", "gate_open_events", "gate_cycles"]
GATE_COLUMNS: Final[tuple[str, ...]] = ("id", "gate_name", "t_open_IST")


@dataclass(frozen=True, slots=True)
class GateOpeningRecord:
    id: str | int
    gate_name: str
    t_open_ist: str

    @property
    def t_open_IST(self) -> str:  # noqa: N802 - preserve report header spelling
        return self.t_open_ist

    def as_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "gate_name": self.gate_name,
            "t_open_IST": self.t_open_ist,
        }


@dataclass(frozen=True, slots=True)
class GateReadResult(Sequence[GateOpeningRecord]):
    """Rows plus the schema source selected by the fallback chain."""

    source_table: GateSourceTable | None
    records: tuple[GateOpeningRecord, ...] = ()

    @property
    def rows(self) -> tuple[GateOpeningRecord, ...]:
        return self.records

    def __iter__(self) -> Iterator[GateOpeningRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    @overload
    def __getitem__(self, index: int) -> GateOpeningRecord: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[GateOpeningRecord, ...]: ...

    def __getitem__(
        self,
        index: int | slice,
    ) -> GateOpeningRecord | tuple[GateOpeningRecord, ...]:
        return self.records[index]


class SQLiteGateReader:
    """Read the first non-empty compatible gate event source."""

    columns: Final[tuple[str, ...]] = GATE_COLUMNS

    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory | str | Path,
    ) -> None:
        if isinstance(connection_factory, SQLiteConnectionFactory):
            self._connections = connection_factory
        else:
            self._connections = SQLiteConnectionFactory(Path(connection_factory))

    def read(self, start_timestamp: float, end_timestamp: float) -> GateReadResult:
        if end_timestamp < start_timestamp:
            raise ValueError("end_timestamp must not be before start_timestamp")

        selected_source: GateSourceTable | None = None
        with self._connections.open() as connection:
            for source in ("gate_openings", "gate_open_events"):
                if not self._table_exists(connection, source):
                    continue
                selected_source = source
                rows = self._read_event_table(
                    connection,
                    source,
                    start_timestamp,
                    end_timestamp,
                )
                if rows:
                    return GateReadResult(source, rows)

            if self._table_exists(connection, "gate_cycles"):
                selected_source = "gate_cycles"
                rows = self._read_cycles(connection, start_timestamp, end_timestamp)
                if rows:
                    return GateReadResult("gate_cycles", rows)

        return GateReadResult(selected_source)

    def read_between(self, start_timestamp: float, end_timestamp: float) -> GateReadResult:
        return self.read(start_timestamp, end_timestamp)

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    @classmethod
    def _read_event_table(
        cls,
        connection: sqlite3.Connection,
        table_name: Literal["gate_openings", "gate_open_events"],
        start_timestamp: float,
        end_timestamp: float,
    ) -> tuple[GateOpeningRecord, ...]:
        # ``table_name`` is constrained to the two static identifiers above;
        # values remain bound SQL parameters.
        rows = connection.execute(
            f"""
            SELECT
                id,
                gate_name,
                datetime(t_open, 'unixepoch', '+5 hours', '+30 minutes') AS t_open_IST
            FROM {table_name}
            WHERE t_open BETWEEN ? AND ?
            ORDER BY t_open
            """,
            (start_timestamp, end_timestamp),
        ).fetchall()
        return cls._to_records(rows)

    @classmethod
    def _read_cycles(
        cls,
        connection: sqlite3.Connection,
        start_timestamp: float,
        end_timestamp: float,
    ) -> tuple[GateOpeningRecord, ...]:
        rows = connection.execute(
            """
            SELECT
                id,
                gate_name,
                datetime(t_open, 'unixepoch', '+5 hours', '+30 minutes') AS t_open_IST
            FROM (
                SELECT id, 'gate1' AS gate_name, t_gate1_open AS t_open
                FROM gate_cycles
                WHERE t_gate1_open BETWEEN ? AND ?
                UNION ALL
                SELECT id, 'gate2' AS gate_name, t_gate2_open AS t_open
                FROM gate_cycles
                WHERE t_gate2_open BETWEEN ? AND ?
            )
            ORDER BY t_open
            """,
            (start_timestamp, end_timestamp, start_timestamp, end_timestamp),
        ).fetchall()
        return cls._to_records(rows)

    @staticmethod
    def _to_records(rows: Sequence[sqlite3.Row]) -> tuple[GateOpeningRecord, ...]:
        return tuple(
            GateOpeningRecord(
                id=row["id"],
                gate_name=str(row["gate_name"]),
                t_open_ist=str(row["t_open_IST"]),
            )
            for row in rows
        )


GateReader = SQLiteGateReader
SqliteGateReader = SQLiteGateReader
