import sqlite3
import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reports.common.caster_config import resolve_enabled_casters
from reports.common.config_loader import load_runtime_config

IST = timezone(timedelta(hours=5, minutes=30))

SHIFTS = {
    "A": ("06:00", "14:00"),
    "B": ("14:00", "22:00"),
    "C": ("22:00", "06:00"),
}


def parse_shift(date_str, shift, cfg):
    shift_key = f"shift_{shift.lower()}"
    configured = {
        str(item["name"]).lower(): (item["start"], item["end"])
        for item in (cfg.get("history", {}) or {}).get("shifts", [])
    }
    start_str, end_str = configured.get(shift_key, SHIFTS[shift])

    start = datetime.strptime(f"{date_str} {start_str}", "%d-%m-%Y %H:%M")
    end = datetime.strptime(f"{date_str} {end_str}", "%d-%m-%Y %H:%M")

    if end <= start:
        end += timedelta(days=1)

    start = start.replace(tzinfo=IST)
    end = end.replace(tzinfo=IST)

    return start.timestamp(), end.timestamp()


def to_ist(ts):
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


def table_exists(cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="DD-MM-YYYY")
    parser.add_argument("--shift", required=True, choices=["A", "B", "C"])
    parser.add_argument("--caster", help="Caster id, for example caster1")

    args = parser.parse_args()

    base_cfg = load_runtime_config()
    casters = resolve_enabled_casters(base_cfg, [args.caster] if args.caster else None)
    caster = casters[0]
    cfg = caster.cfg
    db_path = (PROJECT_ROOT / cfg["database"]["path"]).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    start_ts, end_ts = parse_shift(args.date, args.shift, cfg)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    rows = []
    source_table = "gate_openings"
    if table_exists(cursor, "gate_openings"):
        query = """
        SELECT id, gate_name, t_open
        FROM gate_openings
        WHERE t_open BETWEEN ? AND ?
        ORDER BY t_open
        """
        rows = cursor.execute(query, (start_ts, end_ts)).fetchall()
        source_table = "gate_openings"
    if not rows and table_exists(cursor, "gate_open_events"):
        query = """
        SELECT id, gate_name, t_open
        FROM gate_open_events
        WHERE t_open BETWEEN ? AND ?
        ORDER BY t_open
        """
        rows = cursor.execute(query, (start_ts, end_ts)).fetchall()
        source_table = "gate_open_events"
    if not rows and table_exists(cursor, "gate_cycles"):
        query = """
        SELECT id, gate_name, t_open
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
        """
        rows = cursor.execute(query, (start_ts, end_ts, start_ts, end_ts)).fetchall()
        source_table = "gate_cycles"

    caster_part = f"_{caster.file_token}" if caster.file_token else ""
    csv_name = f"{source_table}{caster_part}_{args.date}_shift_{args.shift}.csv"

    with open(csv_name, "w", newline="") as f:
        writer = csv.writer(f)

        writer.writerow([
            "id",
            "gate_name",
            "t_open_IST",
        ])

        for r in rows:
            writer.writerow([
                r[0],
                r[1],
                to_ist(r[2]),
            ])

    conn.close()

    print(f"Exported {len(rows)} rows from {source_table} to {csv_name}")


if __name__ == "__main__":
    main()
