import sqlite3
import argparse
import csv
from datetime import datetime, timedelta, timezone


from pathlib import Path

DB_PATH = Path("../electrosteel_pipe_detection_prod/var/pipes.db").resolve()
IST = timezone(timedelta(hours=5, minutes=30))

SHIFTS = {
    "A": ("06:00", "14:00"),
    "B": ("14:00", "22:00"),
    "C": ("22:00", "06:00"),
}


def parse_shift(date_str, shift):
    date = datetime.strptime(date_str, "%d-%m-%Y")

    start_str, end_str = SHIFTS[shift]

    start = datetime.strptime(f"{date_str} {start_str}", "%d-%m-%Y %H:%M")
    end = datetime.strptime(f"{date_str} {end_str}", "%d-%m-%Y %H:%M")

    # Shift C crosses midnight
    if shift == "C":
        end += timedelta(days=1)

    start = start.replace(tzinfo=IST)
    end = end.replace(tzinfo=IST)

    return start.timestamp(), end.timestamp()


def to_ist(ts):
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="DD-MM-YYYY")
    parser.add_argument("--shift", required=True, choices=["A", "B", "C"])

    args = parser.parse_args()

    start_ts, end_ts = parse_shift(args.date, args.shift)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
    SELECT id, gate_name, t_open
    FROM gate_open_events
    WHERE t_open BETWEEN ? AND ?
    ORDER BY t_open
    """

    rows = cursor.execute(query, (start_ts, end_ts)).fetchall()

    csv_name = f"gate_open_events_{args.date}_shift_{args.shift}.csv"

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

    print(f"Exported {len(rows)} rows to {csv_name}")


if __name__ == "__main__":
    main()
