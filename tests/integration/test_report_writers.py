from __future__ import annotations

import csv
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from reports_generator.infrastructure.reports import CsvReportWriter, DiagnosisXlsxWriter


@dataclass(frozen=True)
class DiagnosisRow:
    pipe_uid: int
    diagnosis_status: str
    diagnosis_reason: str


def test_csv_writer_supports_raw_and_verified_record_shapes(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.csv"
    verified_path = tmp_path / "verified.csv"
    writer = CsvReportWriter()

    writer.write(raw_path, ({"pipe_uid": 1, "weight": 100.2},))
    writer.write(
        verified_path,
        (record for record in ({"pipe_uid": 1, "verified": True},)),
        fieldnames=("pipe_uid", "verified"),
    )

    with raw_path.open(newline="", encoding="utf-8") as stream:
        assert list(csv.reader(stream)) == [["pipe_uid", "weight"], ["1", "100.2"]]
    with verified_path.open(newline="", encoding="utf-8") as stream:
        assert list(csv.reader(stream)) == [["pipe_uid", "verified"], ["1", "True"]]


def test_csv_writer_emits_headers_for_an_empty_report(tmp_path: Path) -> None:
    output = tmp_path / "empty.csv"
    CsvReportWriter().write(output, (), fieldnames=("pipe_uid", "state"))
    assert output.read_text(encoding="utf-8") == "pipe_uid,state\n"


def test_diagnosis_writer_creates_a_valid_formatted_xlsx_archive(tmp_path: Path) -> None:
    output = tmp_path / "diagnosis.xlsx"
    rows = (
        DiagnosisRow(1, "OK", ""),
        DiagnosisRow(2, "ABNORMAL", "LOADCELL_EXIT_MISSING"),
    )

    assert DiagnosisXlsxWriter().write(output, rows) == output

    with zipfile.ZipFile(output) as workbook:
        assert workbook.testzip() is None
        expected = {
            "[Content_Types].xml",
            "_rels/.rels",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "xl/styles.xml",
            "xl/worksheets/sheet1.xml",
        }
        assert expected.issubset(workbook.namelist())
        for name in expected:
            ElementTree.fromstring(workbook.read(name))
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "LOADCELL_EXIT_MISSING" in sheet
    assert 'r="A3" s="2"' in sheet
    assert 'state="frozen"' in sheet
