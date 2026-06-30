from datetime import datetime, timedelta


class ShiftManager:
    def __init__(self, shifts):
        self.shifts = {
            s["name"].lower(): (s["start"], s["end"])
            for s in shifts
        }

    def window(self, date_str, shift):
        start_s, end_s = self.shifts[shift.lower()]

        start = datetime.strptime(
            f"{date_str} {start_s}", "%d-%m-%Y %H:%M"
        )
        end = datetime.strptime(
            f"{date_str} {end_s}", "%d-%m-%Y %H:%M"
        )

        if end <= start:
            end += timedelta(days=1)

        return start, end
