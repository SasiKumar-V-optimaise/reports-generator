"""SQLite adapters used by report workflows."""

from .connection import ConnectionFactory, SQLiteConnectionFactory
from .gate_reader import (
    GATE_COLUMNS,
    GateOpeningRecord,
    GateReader,
    GateReadResult,
    GateSourceTable,
    SQLiteGateReader,
    SqliteGateReader,
)
from .pipe_reader import (
    PIPE_COLUMNS,
    PipeReader,
    PipeRecord,
    SQLitePipeReader,
    SqlitePipeReader,
)

__all__ = [
    "ConnectionFactory",
    "GATE_COLUMNS",
    "GateOpeningRecord",
    "GateReadResult",
    "GateReader",
    "GateSourceTable",
    "PIPE_COLUMNS",
    "PipeReader",
    "PipeRecord",
    "SQLiteConnectionFactory",
    "SQLiteGateReader",
    "SQLitePipeReader",
    "SqliteGateReader",
    "SqlitePipeReader",
]
