"""SQLite connection creation for report data sources."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SQLiteConnectionFactory:
    """Create consistently configured SQLite connections.

    Report databases are opened read-only by default.  This prevents an input
    path typo from silently creating an empty database and prevents report
    generation from mutating production data.
    """

    database_path: Path
    timeout: float = 5.0
    read_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_path", Path(self.database_path))
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")

    def connect(self) -> sqlite3.Connection:
        """Return a new connection; the caller owns and must close it."""

        path = self.database_path.expanduser().resolve()
        if self.read_only:
            if not path.is_file():
                raise FileNotFoundError(f"SQLite database not found: {path}")
            target = f"{path.as_uri()}?mode=ro"
            connection = sqlite3.connect(
                target,
                timeout=self.timeout,
                uri=True,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(
                str(path),
                timeout=self.timeout,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )

        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def open(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection and always close it at the context boundary."""

        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def __call__(self) -> sqlite3.Connection:
        return self.connect()


# A short spelling retained for callers that treat this as an injectable
# factory rather than as an implementation-specific class.
ConnectionFactory = SQLiteConnectionFactory
