"""Dependency-free XLSX output for pipe diagnosis reports."""

from __future__ import annotations

import math
import numbers
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ._rows import (
    TabularRecord,
    infer_columns,
    normalized_column_names,
    record_values,
)


@dataclass(frozen=True, slots=True)
class DiagnosisWorkbookOptions:
    sheet_name: str = "Diagnosis"
    abnormal_column: str = "diagnosis_status"
    abnormal_value: str = "ABNORMAL"
    maximum_column_width: int = 45

    def __post_init__(self) -> None:
        if not self.sheet_name or len(self.sheet_name) > 31:
            raise ValueError("sheet_name must contain between 1 and 31 characters")
        if any(character in self.sheet_name for character in "[]:*?/\\"):
            raise ValueError("sheet_name contains an Excel-reserved character")
        if self.maximum_column_width < 1:
            raise ValueError("maximum_column_width must be positive")


class DiagnosisXlsxWriter:
    """Write a valid, formatted XLSX workbook using only the standard library."""

    def __init__(self, options: DiagnosisWorkbookOptions | None = None) -> None:
        self._options = options or DiagnosisWorkbookOptions()

    def write(
        self,
        output_path: Path,
        rows: Iterable[TabularRecord],
        columns: Sequence[str] | None = None,
    ) -> Path:
        """Write diagnosis rows without constructing paths or directories."""

        path = Path(output_path)
        materialized = list(rows)
        if columns is not None:
            column_names = normalized_column_names(columns)
        elif materialized:
            column_names = normalized_column_names(infer_columns(materialized[0]))
        else:
            column_names = ()

        values = [record_values(record, column_names) for record in materialized]
        worksheet = self._worksheet_xml(column_names, values)

        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
            workbook.writestr("[Content_Types].xml", _CONTENT_TYPES_XML)
            workbook.writestr("_rels/.rels", _ROOT_RELATIONSHIPS_XML)
            workbook.writestr("xl/workbook.xml", self._workbook_xml())
            workbook.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELATIONSHIPS_XML)
            workbook.writestr("xl/styles.xml", _STYLES_XML)
            workbook.writestr("xl/worksheets/sheet1.xml", worksheet)

        return path

    def _workbook_xml(self) -> str:
        sheet_name = quoteattr(self._options.sheet_name)
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <bookViews><workbookView/></bookViews>
  <sheets><sheet name={sheet_name} sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

    def _worksheet_xml(
        self,
        columns: tuple[str, ...],
        rows: list[tuple[object, ...]],
    ) -> str:
        last_column = _column_name(max(len(columns), 1))
        last_row = max(len(rows) + (1 if columns else 0), 1)
        dimension = f"A1:{last_column}{last_row}" if columns else "A1"

        widths = []
        for index, column in enumerate(columns):
            longest = max(
                [len(column), *[len(_display_value(row[index])) for row in rows]],
                default=len(column),
            )
            width = min(longest + 2, self._options.maximum_column_width)
            widths.append(
                f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
            )

        sheet_rows: list[str] = []
        if columns:
            cells = "".join(
                _cell_xml(1, index, column, style_id=1)
                for index, column in enumerate(columns, start=1)
            )
            sheet_rows.append(f'<row r="1">{cells}</row>')

        abnormal_index = (
            columns.index(self._options.abnormal_column)
            if self._options.abnormal_column in columns
            else None
        )
        start_row = 2 if columns else 1
        for row_number, values in enumerate(rows, start=start_row):
            is_abnormal = (
                abnormal_index is not None
                and str(values[abnormal_index]) == self._options.abnormal_value
            )
            style_id = 2 if is_abnormal else 0
            cells = "".join(
                _cell_xml(row_number, index, value, style_id=style_id)
                for index, value in enumerate(values, start=1)
            )
            sheet_rows.append(f'<row r="{row_number}">{cells}</row>')

        pane = (
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            if columns
            else ""
        )
        columns_xml = f"<cols>{''.join(widths)}</cols>" if widths else ""
        auto_filter = f'<autoFilter ref="{dimension}"/>' if columns else ""
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="{dimension}"/>
  <sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  {columns_xml}
  <sheetData>{"".join(sheet_rows)}</sheetData>
  {auto_filter}
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>'''


def _column_name(column_number: int) -> str:
    name = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _display_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value)


def _clean_xml_text(value: object) -> str:
    text = _display_value(value)
    legal = "".join(
        character for character in text if character in "\t\n\r" or ord(character) >= 0x20
    )
    return escape(legal)


def _cell_xml(
    row_number: int,
    column_number: int,
    value: object,
    *,
    style_id: int,
) -> str:
    reference = f"{_column_name(column_number)}{row_number}"
    style = f' s="{style_id}"' if style_id else ""
    if value is None:
        return f'<c r="{reference}"{style}/>'
    if isinstance(value, bool):
        return f'<c r="{reference}" t="b"{style}><v>{int(value)}</v></c>'
    if isinstance(value, numbers.Real):
        numeric = float(value)
        if math.isfinite(numeric):
            return f'<c r="{reference}"{style}><v>{value}</v></c>'
        return f'<c r="{reference}"{style}/>'
    text = _clean_xml_text(value)
    return (
        f'<c r="{reference}" t="inlineStr"{style}><is><t xml:space="preserve">{text}</t></is></c>'
    )


_CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_ROOT_RELATIONSHIPS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_RELATIONSHIPS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>
    <font><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="4">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F2937"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFF0000"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium9" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>"""


XlsxWriter = DiagnosisXlsxWriter
XLSXWriter = DiagnosisXlsxWriter
