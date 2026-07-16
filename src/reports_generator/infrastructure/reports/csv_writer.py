"""Streaming CSV report output."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from itertools import chain
from pathlib import Path

from ._rows import (
    TabularRecord,
    infer_columns,
    normalized_column_names,
    record_values,
)


class CsvReportWriter:
    """Write mapping or dataclass records to a caller-selected path."""

    def __init__(self, *, encoding: str = "utf-8", include_header: bool = True) -> None:
        self._encoding = encoding
        self._include_header = include_header

    def write(
        self,
        output_path: Path,
        rows: Iterable[TabularRecord],
        fieldnames: Sequence[str] | None = None,
    ) -> Path:
        """Stream rows into ``output_path`` without creating its parent.

        Column order is taken from ``fieldnames`` when supplied, otherwise from
        the first mapping/dataclass/named-tuple record.  Supplying field names
        is therefore useful when an empty report must still contain headers.
        """

        path = Path(output_path)
        iterator = iter(rows)
        try:
            first = next(iterator)
        except StopIteration:
            first = None

        if fieldnames is not None:
            columns = normalized_column_names(fieldnames)
        elif first is not None:
            columns = normalized_column_names(infer_columns(first))
        else:
            columns = ()

        with path.open("w", encoding=self._encoding, newline="") as stream:
            writer = csv.writer(stream)
            if self._include_header and columns:
                writer.writerow(columns)
            if first is not None:
                for row in chain((first,), iterator):
                    writer.writerow(record_values(row, columns))

        return path


CSVWriter = CsvReportWriter
CsvWriter = CsvReportWriter
