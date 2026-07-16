"""Typed normalization shared by tabular file adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from typing import TypeAlias

TabularRecord: TypeAlias = Mapping[str, object] | object


def infer_columns(record: TabularRecord) -> tuple[str, ...]:
    if isinstance(record, Mapping):
        return tuple(str(key) for key in record)
    if is_dataclass(record) and not isinstance(record, type):
        return tuple(field.name for field in fields(record))
    as_dict = getattr(record, "_asdict", None)
    if callable(as_dict):
        return tuple(str(key) for key in as_dict())
    raise TypeError(
        "fieldnames/columns are required for records that are not mappings, "
        "dataclass instances, or named tuples"
    )


def record_values(
    record: TabularRecord,
    columns: Sequence[str],
) -> tuple[object, ...]:
    if isinstance(record, Mapping):
        return tuple(record.get(column, "") for column in columns)
    if is_dataclass(record) and not isinstance(record, type):
        return tuple(getattr(record, column, "") for column in columns)
    as_dict = getattr(record, "_asdict", None)
    if callable(as_dict):
        values = as_dict()
        return tuple(values.get(column, "") for column in columns)
    if isinstance(record, Sequence) and not isinstance(
        record,
        (str, bytes, bytearray),
    ):
        values = tuple(record)
        if len(values) != len(columns):
            raise ValueError(
                f"record contains {len(values)} values but {len(columns)} columns were supplied"
            )
        return values
    raise TypeError(f"unsupported tabular record type: {type(record).__name__}")


def normalized_column_names(columns: Sequence[str]) -> tuple[str, ...]:
    names = tuple(str(column) for column in columns)
    if len(names) != len(set(names)):
        raise ValueError("column names must be unique")
    if any(not name for name in names):
        raise ValueError("column names must not be empty")
    return names
