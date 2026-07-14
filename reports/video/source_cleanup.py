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
    image_paths: list[str | Path] | None = None,
    text_paths: list[str | Path] | None = None,
    prune_empty_date_dirs: bool = True,
) -> dict:
    """
    Delete the source image/text files or folders used by a completed shift video.

    When exact paths are provided, only those files are removed. Empty shift/date
    folders are pruned afterward, which keeps late re-runs from deleting newer
    files that may share the same Shift_C folder on the next date.
    """
    source_dirs = shift_source_dirs(history_root, date_str, shift)
    source_files = _source_files(image_paths, text_paths)
    date_dirs = {path.parent for path in source_dirs}
    summary = {
        "source_dirs": [str(path) for path in source_dirs],
        "deleted_files": [],
        "missing_files": [],
        "failed_files": {},
        "deleted_dirs": [],
        "missing_dirs": [],
        "failed_dirs": {},
        "removed_empty_date_dirs": [],
        "kept_date_dirs": [],
    }

    if source_files:
        date_dirs.update(path.parent.parent for path in source_files)
        for path in sorted(source_files):
            if not path.exists():
                summary["missing_files"].append(str(path))
                continue
            if not path.is_file():
                summary["failed_files"][str(path)] = "Path exists but is not a file"
                logger.warning("Shift source cleanup skipped non-file path: %s", path)
                continue

            try:
                path.unlink()
            except Exception as exc:
                summary["failed_files"][str(path)] = str(exc)
                logger.warning("Failed to delete shift source file | path=%s | error=%s", path, exc)
                continue

            summary["deleted_files"].append(str(path))
            logger.info("Deleted shift source file: %s", path)

        _remove_empty_source_dirs(source_dirs, summary)
        _remove_empty_date_dirs(sorted(date_dirs), summary, prune_empty_date_dirs)
        return summary

    for directory in source_dirs:
        if not directory.exists():
            summary["missing_dirs"].append(str(directory))
            continue
        if not directory.is_dir():
            summary["failed_dirs"][str(directory)] = "Path exists but is not a directory"
            logger.warning("Shift source cleanup skipped non-directory path: %s", directory)
            continue

        try:
            shutil.rmtree(directory)
        except Exception as exc:
            summary["failed_dirs"][str(directory)] = str(exc)
            logger.warning("Failed to delete shift source folder | path=%s | error=%s", directory, exc)
            continue

        summary["deleted_dirs"].append(str(directory))
        logger.info("Deleted shift source folder: %s", directory)

    _remove_empty_date_dirs(sorted(date_dirs), summary, prune_empty_date_dirs)
    return summary


def text_path_for_image(image_path: Path | str) -> Path:
    image_path = Path(image_path)
    return image_path.parent.parent / image_path.parent.name.replace("_img", "_text") / f"{image_path.stem}.txt"


def _source_files(
    image_paths: list[str | Path] | None,
    text_paths: list[str | Path] | None,
) -> set[Path]:
    files = {Path(path) for path in image_paths or []}
    files.update(text_path_for_image(path) for path in image_paths or [])
    files.update(Path(path) for path in text_paths or [])
    return files


def _remove_empty_source_dirs(source_dirs: list[Path], summary: dict):
    for directory in source_dirs:
        if not directory.exists():
            summary["missing_dirs"].append(str(directory))
            continue
        if not directory.is_dir():
            summary["failed_dirs"][str(directory)] = "Path exists but is not a directory"
            logger.warning("Shift source cleanup skipped non-directory path: %s", directory)
            continue
        try:
            if any(directory.iterdir()):
                continue
            directory.rmdir()
        except Exception as exc:
            summary["failed_dirs"][str(directory)] = str(exc)
            logger.warning("Failed to remove empty shift source folder | path=%s | error=%s", directory, exc)
            continue

        summary["deleted_dirs"].append(str(directory))
        logger.info("Removed empty shift source folder: %s", directory)


def _remove_empty_date_dirs(date_dirs: list[Path], summary: dict, enabled: bool):
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
            logger.warning("Failed to remove empty history date folder | path=%s | error=%s", date_dir, exc)
            continue

        summary["removed_empty_date_dirs"].append(str(date_dir))
        logger.info("Removed empty history date folder: %s", date_dir)


def _shift_letter(value: str) -> str:
    text = str(value).strip()
    if text.lower().startswith("shift_"):
        text = text.split("_", 1)[1]
    text = text.upper()
    if text not in {"A", "B", "C"}:
        raise ValueError("Invalid shift. Use A, B, C, Shift_A, Shift_B, or Shift_C")
    return text