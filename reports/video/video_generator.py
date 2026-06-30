import cv2
import glob
import yaml
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


class ShiftVideoGenerator:
    """
    Production-grade shift video generator
    - YAML driven
    - logging based
    - timestamp range reporting
    """

    # ---------------- INIT ----------------
    def __init__(self, date_str: str, shift: str):

        self.date_str = date_str
        self.shift = shift.upper()
        self.date_obj = datetime.strptime(date_str, "%d-%m-%Y")

        self.root = Path(__file__).resolve().parents[2]

        with open(self.root / "config/runtime.yaml") as f:
            cfg = yaml.safe_load(f)

        self.video_cfg = cfg["video"]
        self.image_root = (self.root / cfg["history"]["image_root"]).resolve()

        # Setup resolution config (clean version without mode)
        self.res_cfg = self.video_cfg.get("resolution", {})

        self.output_dir = self.root / self.video_cfg["output_dir"]
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.output_path = (
            self.output_dir /
            f"{date_str}_shift_{self.shift.lower()}.mp4"
        )

        logger.info(
            "VideoGenerator initialized | date=%s | shift=%s",
            self.date_str, self.shift
        )

    # ---------------- GENERATE ----------------
    def generate(self):

        images = self._collect_images()
        if not images:
            raise RuntimeError("No images found for shift")

        start_ts = self._timestamp_from_name(images[0])
        end_ts = self._timestamp_from_name(images[-1])

        logger.info(
            "Generating video | shift=%s | images=%s | range=%s → %s",
            self.shift, len(images), start_ts, end_ts
        )

        first = cv2.imread(images[0])
        if first is None:
            raise RuntimeError("Failed to read first image")

        h, w = first.shape[:2]
        w, h = self._resolve_resolution(w, h)

        fps_cfg = self.video_cfg.get("fps", 10)

        logger.info("Resolution=%sx%s | FPS=%s", w, h, fps_cfg)

        writer = cv2.VideoWriter(
            str(self.output_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps_cfg,
            (w, h),
        )
        if not writer.isOpened():
            raise RuntimeError(f"Failed to open video writer: {self.output_path}")

        start_time = time.time()
        total = len(images)

        for i, img in enumerate(images, 1):

            frame = cv2.imread(img)
            if frame is None:
                logger.warning("Skipping unreadable frame: %s", img)
                continue

            if (frame.shape[1], frame.shape[0]) != (w, h):
                frame = cv2.resize(frame, (w, h))

            ts = self._timestamp_from_name(img)
            if ts:
                cv2.putText(
                    frame, ts, (20, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 255), 2, cv2.LINE_AA
                )

            writer.write(frame)

        writer.release()

        total_time = int(time.time() - start_time)

        logger.info(
            "Video created successfully | path=%s | duration=%ss",
            self.output_path, total_time
        )

        return str(self.output_path)

    # ---------------- RESOLUTION ----------------
    def _resolve_resolution(self, w, h):

        width = self.res_cfg.get("width", "auto")
        height = self.res_cfg.get("height", "auto")

        if width == "auto":
            width = w
        if height == "auto":
            height = h

        return int(width), int(height)

    # ---------------- IMAGE COLLECTION ----------------
    def _collect_images(self):

        def day_images(d):
            path = self.image_root / d.strftime("%Y_%m_%d") / f"Shift_{self.shift}_img"
            return sorted(glob.glob(str(path / "*.jpeg")))

        if self.shift in ["A", "B"]:
            return day_images(self.date_obj)

        # Shift C crosses midnight
        next_day = self.date_obj + timedelta(days=1)

        today = [i for i in day_images(self.date_obj) if self._hour(i) >= 22]
        nxt = [i for i in day_images(next_day) if self._hour(i) < 6]

        return sorted(today + nxt)

    # ---------------- TIMESTAMP ----------------
    @staticmethod
    def _timestamp_from_name(path):
        try:
            name = Path(path).stem.split("_")[-1]
            dd, mm, yyyy, hh, mi, ss = name.split("-")[:6]
            return f"{yyyy}-{mm}-{dd} {hh}:{mi}:{ss}"
        except Exception:
            return None

    # ---------------- HOUR ----------------
    @staticmethod
    def _hour(path):
        try:
            return int(Path(path).stem.split("_")[-1].split("-")[3])
        except Exception:
            return -1


# ---------------- CLI ----------------
if __name__ == "__main__":
    import argparse
    import logging
    import yaml

    root = Path(__file__).resolve().parents[2]
    with open(root / "config/runtime.yaml") as f:
        cfg = yaml.safe_load(f)

    level_name = (cfg.get("logging", {}) or {}).get("level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(description="Generate shift video")
    parser.add_argument("--date", required=True)
    parser.add_argument("shift", choices=["shift_a", "shift_b", "shift_c"])

    args = parser.parse_args()
    shift_letter = args.shift.split("_")[1].upper()

    ShiftVideoGenerator(args.date, shift_letter).generate()
