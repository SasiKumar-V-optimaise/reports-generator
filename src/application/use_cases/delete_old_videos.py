from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
from src.infrastructure.config.caster_config_resolver import build_caster_runtime_config, resolve_enabled_casters
from src.infrastructure.config.runtime_config_loader import load_runtime_config


logger = logging.getLogger(__name__)
DATE_PATTERNS = (
    (re.compile(r"^(\d{2}-\d{2}-\d{4})"), "%d-%m-%Y"),
    (re.compile(r"(?<!\d)(\d{8})(?!\d)"), "%d%m%Y"),
)


def video_date(path: Path) -> date | None:
    for pattern, fmt in DATE_PATTERNS:
        match = pattern.search(path.stem)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(1), fmt).date()
        except ValueError:
            return None
    return None


def configured_caster_cfgs(cfg: dict) -> list[dict]:
    casters = cfg.get("casters")
    if not isinstance(casters, dict):
        return [caster.cfg for caster in resolve_enabled_casters(cfg)]

    defaults = casters.get("defaults") or {}
    items = [item for item in casters.get("items", []) if isinstance(item, dict) and item.get("id")]
    if not items:
        raise RuntimeError("No casters configured in config/runtime.yaml")
    return [build_caster_runtime_config(cfg, item, defaults) for item in items]


def video_dirs(caster_cfg: dict, include_overlay: bool) -> list[Path]:
    video_cfg = caster_cfg.get("video", {}) or {}
    paths = [video_cfg.get("output_dir")]
    if include_overlay:
        paths.append(video_cfg.get("overlay_output_dir"))
    return [(PROJECT_ROOT / Path(str(path))).resolve() for path in paths if path]


def cleanup_old_videos(cfg: dict, *, dry_run: bool = False, today: date | None = None) -> dict[str, int]:
    retention_cfg = cfg.get("video_retention", {}) or {}
    keep_days = int(retention_cfg.get("keep_days", 0))
    if keep_days < 1:
        raise RuntimeError("video_retention.keep_days must be greater than 0")

    cutoff = (today or date.today()) - timedelta(days=keep_days - 1)
    include_overlay = bool(retention_cfg.get("include_overlay_videos", True))
    summary = {"scanned": 0, "kept": 0, "deleted": 0, "would_delete": 0, "skipped": 0, "missing_dirs": 0}

    for caster_cfg in configured_caster_cfgs(cfg):
        for directory in video_dirs(caster_cfg, include_overlay):
            if not directory.exists():
                summary["missing_dirs"] += 1
                continue

            for video in sorted(directory.glob("*.mp4")):
                summary["scanned"] += 1
                created_on = video_date(video)
                if created_on is None:
                    summary["skipped"] += 1
                    logger.warning("Skipping video with unknown date: %s", video)
                    continue

                if created_on >= cutoff:
                    summary["kept"] += 1
                    continue

                if dry_run:
                    summary["would_delete"] += 1
                    logger.info("Would delete old video: %s", video)
                else:
                    video.unlink()
                    summary["deleted"] += 1
                    logger.info("Deleted old video: %s", video)

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete generated videos older than video_retention.keep_days.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_runtime_config()
    level = str((cfg.get("logging", {}) or {}).get("level", "INFO")).upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")

    summary = cleanup_old_videos(cfg, dry_run=args.dry_run)
    print("Video cleanup complete | " + " ".join(f"{key}={value}" for key, value in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


