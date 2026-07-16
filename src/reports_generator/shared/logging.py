import logging
from pathlib import Path


def configure_logging(log_root: Path, level: str = "INFO") -> logging.Logger:
    log_root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("reports_generator")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        h = logging.FileHandler(log_root / "application.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger
