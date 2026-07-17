from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path


logger = logging.getLogger(__name__)


def shift_source_dirs(history_root: Path | str, date_str: str, shift: str) -> list[Path]:
    """Return image/text source folders for a completed shift."""
    history_root = Path(history_root)
    shift_letter = _shift_letter(shift)
    date_obj = datetime.strptime(date_str, "%d-%m-%Y")

    dates = [date_obj]
    if shift_letter == "C":
        dates.append(date_obj + timedelta(days=1))

    dirs: list[Path] = []
    for day in dates:
        date_dir = history_root / day.strftime("%Y_%m_%d")
        dirs.append(date_dir / f"Shift_{shift_letter}_img")
        dirs.append(date_dir / f"Shift_{shift_letter}_text")
    return dirs


def cleanup_shift_sources(
    history_root: Path | str,
    date_str: str,
    shift: str,
    *,
    prune_empty_date_dirs: bool = True,
    caster_name: str | None = None,
) -> dict:
    """
    Delete completed shift source image/text folders after video success.

    This removes whole `Shift_X_img` and `Shift_X_text` folders instead of
    unlinking every image/text file one by one. That keeps cleanup fast and
    keeps production logs compact on the Jetson.
    """
    source_dirs = shift_source_dirs(history_root, date_str, shift)
    date_dirs = sorted({path.parent for path in source_dirs})
    caster_text = caster_name or "unknown caster"
    summary = {
        "source_dirs": [str(path) for path in source_dirs],
        "deleted_dirs": [],
        "missing_dirs": [],
        "failed_dirs": {},
        "removed_empty_date_dirs": [],
        "kept_date_dirs": [],
    }

    logger.info(
        "Shift source folder cleanup started | caster=%s | date=%s | shift=%s | folders=%s",
        caster_text,
        date_str,
        _shift_letter(shift),
        len(source_dirs),
    )

    for directory in source_dirs:
        if not directory.exists():
            summary["missing_dirs"].append(str(directory))
            logger.info("Shift source folder missing; skipping | caster=%s | path=%s", caster_text, directory)
            continue
        if not directory.is_dir():
            summary["failed_dirs"][str(directory)] = "Path exists but is not a directory"
            logger.warning("Shift source cleanup skipped non-directory path | caster=%s | path=%s", caster_text, directory)
            continue

        try:
            shutil.rmtree(directory)
        except Exception as exc:
            summary["failed_dirs"][str(directory)] = str(exc)
            logger.warning("Failed to delete shift source folder | caster=%s | path=%s | error=%s", caster_text, directory, exc)
            continue

        summary["deleted_dirs"].append(str(directory))
        logger.info("Deleted shift source folder | caster=%s | path=%s", caster_text, directory)

    _remove_empty_date_dirs(date_dirs, summary, prune_empty_date_dirs, caster_text)

    logger.info(
        "Shift source folder cleanup finished | caster=%s | date=%s | shift=%s | deleted_folders=%s | missing_folders=%s | removed_date_folders=%s | failed_folders=%s",
        caster_text,
        date_str,
        _shift_letter(shift),
        len(summary["deleted_dirs"]),
        len(summary["missing_dirs"]),
        len(summary["removed_empty_date_dirs"]),
        len(summary["failed_dirs"]),
    )
    return summary


def _remove_empty_date_dirs(date_dirs: list[Path], summary: dict, enabled: bool, caster_text: str):
    if not enabled:
        return

    for date_dir in date_dirs:
        if not date_dir.exists():
            continue
        try:
            if any(date_dir.iterdir()):
                summary["kept_date_dirs"].append(str(date_dir))
                continue
            date_dir.rmdir()
        except Exception as exc:
            summary["failed_dirs"][str(date_dir)] = str(exc)
            logger.warning("Failed to remove empty history date folder | caster=%s | path=%s | error=%s", caster_text, date_dir, exc)
            continue

        summary["removed_empty_date_dirs"].append(str(date_dir))
        logger.info("Removed empty history date folder | caster=%s | path=%s", caster_text, date_dir)


def _shift_letter(value: str) -> str:
    text = str(value).strip()
    if text.lower().startswith("shift_"):
        text = text.split("_", 1)[1]
    text = text.upper()
    if text not in {"A", "B", "C"}:
        raise ValueError("Invalid shift. Use A, B, C, Shift_A, Shift_B, or Shift_C")
    return text

