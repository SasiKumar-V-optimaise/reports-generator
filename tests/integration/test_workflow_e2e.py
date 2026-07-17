from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import yaml

from reports_generator.cli.main import main
from reports_generator.infrastructure.config.loader import clear_config_cache

IST = timezone(timedelta(hours=5, minutes=30))


def _epoch(value: datetime) -> float:
    return value.replace(tzinfo=IST).timestamp()


def _write_config(root: Path) -> None:
    source = root / "source"
    source.mkdir()
    (source / "rois.yaml").write_text("{}\n", encoding="utf-8")
    config = root / "config"
    config.mkdir()
    runtime = {
        "paths": {
            "output_root": "outputs",
            "state_root": "runtime/state",
            "temp_root": "runtime/temp",
            "log_root": "logs",
        },
        "history": {
            "shifts": [
                {"name": "Shift_A", "start": "06:00", "end": "14:00"},
                {"name": "Shift_B", "start": "14:00", "end": "22:00"},
                {"name": "Shift_C", "start": "22:00", "end": "06:00"},
            ]
        },
        "casters": [
            {
                "id": "caster-test",
                "display_name": "Test Caster",
                "active": True,
                "database_directory": "source",
                "database_file": "pipes.db",
                "history_directory": "source/history",
                "recording_directory": "source/recordings",
                "roi_path": "source/rois.yaml",
            },
            {
                "id": "caster-second",
                "display_name": "Second Test Caster",
                "active": True,
                "database_directory": "source",
                "database_file": "pipes.db",
                "history_directory": "source/history",
                "recording_directory": "source/recordings",
                "roi_path": "source/rois.yaml",
            },
        ],
        "diagnosis": {
            "t_origin_gap_min": "00:01:30",
            "t_origin_gap_max": "00:03:20",
        },
        "verification": {
            "mode": "loadcell",
            "gate_open_max_interval_seconds": 120,
        },
        "missing_loadcell_video": {
            "enabled": True,
            "pre_origin_seconds": 60,
            "clip_duration_seconds": 300,
        },
        "email": {
            "smtp_server": "smtp.example.test",
            "smtp_port": 587,
            "sender": "reports@example.test",
            "password_env": "EMAIL_APP_PASSWORD",
            "recipients": [],
            "test_recipients": [],
            "diagnosis_recipients": [],
        },
        "upload": {
            "enabled": False,
            "remote": "test",
            "base_path": "reports",
            "raw_csv_directory": "csv",
            "video_directory": "videos",
        },
        "video_retention": {"keep_days": 5},
        "storage": {"path": ".", "alert_threshold_percent": 90},
        "logging": {"level": "INFO"},
    }
    video = {
        "video": {
            "fps": 5,
            "codec": "mp4v",
            "input_images_have_overlay": False,
            "output_resolution": {"width": 64, "height": 48},
            "overlay": {
                "font_scale": 0.3,
                "thickness": 1,
                "color": [0, 255, 255],
                "margin_bottom": 5,
                "margin_left": 2,
            },
        }
    }
    (config / "runtime.yaml").write_text(
        yaml.safe_dump(runtime, sort_keys=False), encoding="utf-8"
    )
    (config / "video.yaml").write_text(
        yaml.safe_dump(video, sort_keys=False), encoding="utf-8"
    )


def _write_database(root: Path) -> None:
    database = root / "source" / "pipes.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE pipes (
                pipe_uid INTEGER,
                origin TEXT,
                pipe_checkpoint INTEGER,
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
        )
        first = datetime(2026, 7, 15, 22, 0, 10)
        second = datetime(2026, 7, 15, 22, 2, 10)
        connection.executemany(
            "INSERT INTO pipes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    1,
                    "left",
                    0,
                    _epoch(first),
                    _epoch(first + timedelta(seconds=5)),
                    _epoch(first + timedelta(seconds=15)),
                    100.0,
                    "good",
                    8,
                    "done",
                    _epoch(first + timedelta(seconds=20)),
                ),
                (
                    2,
                    "right",
                    1,
                    _epoch(second),
                    None,
                    None,
                    101.0,
                    "good",
                    8,
                    "done",
                    _epoch(second + timedelta(seconds=20)),
                ),
            ],
        )
        connection.execute(
            "CREATE TABLE gate_openings (id INTEGER, gate_name TEXT, t_open REAL)"
        )


def _write_images(root: Path) -> tuple[Path, Path]:
    directory = root / "source" / "history" / "2026_07_15" / "Shift_C_img"
    directory.mkdir(parents=True)
    first = directory / "frame_15-07-2026-22-00-10.jpeg"
    second = directory / "frame_15-07-2026-22-02-10.jpeg"
    assert cv2.imwrite(str(first), np.full((48, 64, 3), 40, dtype=np.uint8))
    assert cv2.imwrite(str(second), np.full((48, 64, 3), 80, dtype=np.uint8))
    return first, second


def test_cli_runs_real_local_workflow_without_external_side_effects(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_config(tmp_path)
    _write_database(tmp_path)
    source_images = _write_images(tmp_path)
    clear_config_cache()
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "report",
            "--date",
            "2026-07-15",
            "--shift",
            "C",
            "--casters",
            "caster-test",
            "caster-second",
            "--test",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "caster-test | report | OK" in output
    assert "caster-test | video | OK" in output
    assert "caster-second | report | OK" in output
    assert "caster-second | video | OK" in output
    assert "external upload skipped in --test mode" in output
    assert "external notification skipped in --test mode" in output
    assert output.rstrip().endswith("True")

    caster_root = tmp_path / "outputs" / "caster-test"
    raw_path = caster_root / "raw_csv" / "15-07-2026_shift_C.csv"
    verified_path = caster_root / "verified_csv" / "15-07-2026_shift_C_verified.csv"
    diagnosis_path = caster_root / "diagnosis" / "15-07-2026_shift_C_diagnosis.xlsx"
    video_path = caster_root / "videos" / "15-07-2026_shift_C.mp4"
    assert raw_path.is_file()
    assert verified_path.is_file()
    assert diagnosis_path.is_file()
    assert video_path.is_file() and video_path.stat().st_size > 0
    assert (
        tmp_path / "outputs" / "caster-second" / "videos" / "15-07-2026_shift_C.mp4"
    ).is_file()

    with raw_path.open(newline="", encoding="utf-8") as stream:
        assert len(list(csv.DictReader(stream))) == 2
    with verified_path.open(newline="", encoding="utf-8") as stream:
        verified = list(csv.DictReader(stream))
    assert [row["pipe_uid"] for row in verified] == ["2", "1"]
    assert {row["verification_reason"] for row in verified} == {
        "CHECKPOINT",
        "NOT_REQUIRED",
    }

    state_path = tmp_path / "runtime" / "state" / "2026-07-15_C.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["success"] is True
    assert {item["caster_id"] for item in state["caster_results"]} == {
        "caster-test",
        "caster-second",
    }
    assert all(path.is_file() for path in source_images)
    clear_config_cache()
