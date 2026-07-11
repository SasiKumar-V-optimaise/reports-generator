from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reports.common.config_loader import load_runtime_config
from reports.common.email_sender import EmailSender


@dataclass(frozen=True)
class DiskUsage:
    filesystem: str
    use_percent: int
    mountpoint: str


def _parse_df_line(line: str) -> DiskUsage:
    parts = line.split()
    if len(parts) < 6:
        raise RuntimeError(f"Could not parse df output line: {line}")

    usage = parts[4].rstrip("%")
    if not usage.isdigit():
        raise RuntimeError(f"Could not parse disk usage from df output line: {line}")

    return DiskUsage(
        filesystem=parts[0],
        use_percent=int(usage),
        mountpoint=parts[5],
    )


def get_device_usage(device: str) -> DiskUsage | None:
    output = subprocess.check_output(["df", "-P"], text=True)
    for line in output.splitlines()[1:]:
        usage = _parse_df_line(line)
        if usage.filesystem == device:
            return usage
    return None


def normalize_recipients(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]

    recipients: list[str] = []
    for item in value:
        recipients.extend(part.strip() for part in str(item).replace(",", " ").split() if part.strip())
    return recipients


def recipients_from_config(cfg: dict, mode: str) -> list[str]:
    email_cfg = cfg.get("email", {}) or {}
    key = "test_recipients" if mode == "test" else "recipients"
    recipients = normalize_recipients(email_cfg.get(key))
    if not recipients:
        raise RuntimeError(f"No email.{key} configured in config/runtime.yaml")
    return recipients


def storage_alert_settings(cfg: dict, args: argparse.Namespace) -> tuple[str, int, str]:
    alert_cfg = cfg.get("jetson_storage_alert", {}) or {}
    device = args.device or alert_cfg.get("device")
    threshold = args.threshold if args.threshold is not None else alert_cfg.get("threshold_percent")
    recipient_mode = args.recipient_mode or alert_cfg.get("recipient_mode", "test")

    if not device:
        raise RuntimeError("No jetson_storage_alert.device configured in config/runtime.yaml")
    if threshold is None:
        raise RuntimeError("No jetson_storage_alert.threshold_percent configured in config/runtime.yaml")

    try:
        threshold = int(threshold)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("jetson_storage_alert.threshold_percent must be an integer") from exc

    if threshold < 1:
        raise RuntimeError("jetson_storage_alert.threshold_percent must be greater than 0")
    if recipient_mode not in {"test", "production"}:
        raise RuntimeError("jetson_storage_alert.recipient_mode must be 'test' or 'production'")

    return str(device), threshold, str(recipient_mode)


def build_alert_body(usage: DiskUsage, threshold: int, device: str) -> str:
    disk_status = subprocess.check_output(["df", "-hP", usage.mountpoint], text=True).strip()
    return "\n".join(
        [
            "Jetson storage usage is above the configured threshold.",
            "",
            f"Filesystem: {usage.filesystem}",
            f"Mounted on: {usage.mountpoint}",
            f"Usage: {usage.use_percent}%",
            f"Threshold: {threshold}%",
            f"Checked device: {device}",
            f"Checked at: {datetime.now().isoformat(timespec='seconds')}",
            "",
            "Current disk status:",
            disk_status,
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send an email when Jetson storage usage is above threshold.")
    parser.add_argument("--device", help="Override jetson_storage_alert.device from runtime.yaml")
    parser.add_argument("--threshold", type=int, help="Override jetson_storage_alert.threshold_percent from runtime.yaml")
    parser.add_argument(
        "--recipient-mode",
        choices=["test", "production"],
        help="Override jetson_storage_alert.recipient_mode from runtime.yaml",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_runtime_config()
    device, threshold, recipient_mode = storage_alert_settings(cfg, args)

    usage = get_device_usage(device)
    if usage is None:
        raise RuntimeError(f"Storage device {device} was not found in df output")

    if usage.use_percent <= threshold:
        print(f"{usage.filesystem} usage is {usage.use_percent}%, below threshold {threshold}%.")
        return 0

    recipients = recipients_from_config(cfg, recipient_mode)
    subject_prefix = "[TEST] " if recipient_mode == "test" else ""
    subject = f"{subject_prefix}Jetson storage alert: {usage.filesystem} is {usage.use_percent}% full"
    body = build_alert_body(usage, threshold, device)

    EmailSender(cfg=cfg).send_text(subject, body, recipients=recipients)
    print(f"Email sent to {', '.join(recipients)} because {usage.filesystem} is {usage.use_percent}% full.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())