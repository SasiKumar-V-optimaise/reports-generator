"""Read the report-facing pipe projection from SQLite."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from .connection import SQLiteConnectionFactory

SQLiteValue: TypeAlias = str | int | float | bytes | None

PIPE_COLUMNS: Final[tuple[str, ...]] = (
    "pipe_uid",
    "origin",
    "pipe_checkpoint",
    "t_origin",
    "t_loadcell_enter",
    "t_loadcell_exit",
    "weight",
    "weight_quality",
    "weight_samples",
    "state",
    "last_seen_ts",
)

_REQUIRED_DATABASE_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "pipe_uid",
        "origin",
        "t_origin",
        "t_loadcell_enter",
        "t_loadcell_exit",
        "weight",
        "weight_quality",
        "weight_samples",
        "state",
        "last_seen_ts",
    }
)


@dataclass(frozen=True, slots=True)
class PipeRecord:
    """One pipe row as displayed in a generated report."""

    pipe_uid: SQLiteValue
    origin: SQLiteValue
    pipe_checkpoint: SQLiteValue
    t_origin: str | None
    t_loadcell_enter: str | None
    t_loadcell_exit: str | None
    weight: SQLiteValue
    weight_quality: SQLiteValue
    weight_samples: SQLiteValue
    state: SQLiteValue
    last_seen_ts: str | None

    def as_dict(self) -> dict[str, SQLiteValue]:
        return {column: getattr(self, column) for column in PIPE_COLUMNS}


class SQLitePipeReader:
    """Fetch only columns required by pipe CSV and diagnosis reports."""

    columns: Final[tuple[str, ...]] = PIPE_COLUMNS

    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory | str | Path,
    ) -> None:
        if isinstance(connection_factory, SQLiteConnectionFactory):
            self._connections = connection_factory
        else:
            self._connections = SQLiteConnectionFactory(Path(connection_factory))

    def read(self, start_timestamp: float, end_timestamp: float) -> tuple[PipeRecord, ...]:
        """Return pipes whose origin timestamp is inside the inclusive range.

        Epoch values are converted to the same second-resolution IST display
        strings used by the legacy exporter.  Older databases that do not have
        ``pipe_checkpoint`` receive a numeric zero in that projection.
        """

        if end_timestamp < start_timestamp:
            raise ValueError("end_timestamp must not be before start_timestamp")

        with self._connections.open() as connection:
            table_columns = self._table_columns(connection)
            missing = _REQUIRED_DATABASE_COLUMNS.difference(table_columns)
            if missing:
                names = ", ".join(sorted(missing))
                raise sqlite3.OperationalError(f"pipes table is missing required columns: {names}")

            checkpoint_expression = (
                "pipe_checkpoint" if "pipe_checkpoint" in table_columns else "0 AS pipe_checkpoint"
            )
            rows = connection.execute(
                f"""
                SELECT
                    pipe_uid,
                    origin,
                    {checkpoint_expression},
                    datetime(t_origin, 'unixepoch', '+5 hours', '+30 minutes') AS t_origin,
                    datetime(t_loadcell_enter, 'unixepoch', '+5 hours', '+30 minutes')
                        AS t_loadcell_enter,
                    datetime(t_loadcell_exit, 'unixepoch', '+5 hours', '+30 minutes')
                        AS t_loadcell_exit,
                    weight,
                    weight_quality,
                    weight_samples,
                    state,
                    datetime(last_seen_ts, 'unixepoch', '+5 hours', '+30 minutes')
                        AS last_seen_ts
                FROM pipes
                WHERE t_origin BETWEEN ? AND ?
                ORDER BY t_origin DESC
                """,
                (start_timestamp, end_timestamp),
            ).fetchall()

        return tuple(PipeRecord(**{column: row[column] for column in PIPE_COLUMNS}) for row in rows)

    def read_between(
        self,
        start_timestamp: float,
        end_timestamp: float,
    ) -> tuple[PipeRecord, ...]:
        """Explicitly named alias for dependency-injected application code."""

        return self.read(start_timestamp, end_timestamp)

    @staticmethod
    def _table_columns(connection: sqlite3.Connection) -> set[str]:
        rows = connection.execute("PRAGMA table_info(pipes)").fetchall()
        return {str(row["name"]) for row in rows}


PipeReader = SQLitePipeReader
SqlitePipeReader = SQLitePipeReader
