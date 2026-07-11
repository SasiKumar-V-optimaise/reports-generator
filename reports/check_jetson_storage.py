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
    parser.add_argument("--device", default="/dev/nvme0n1p1")
    parser.add_argument("--threshold", type=int, default=90)
    parser.add_argument(
        "--recipient-mode",
        choices=["test", "production"],
        default="test",
        help="test uses email.test_recipients; production uses email.recipients",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.threshold < 1:
        raise RuntimeError("--threshold must be greater than 0")

    usage = get_device_usage(args.device)
    if usage is None:
        raise RuntimeError(f"Storage device {args.device} was not found in df output")

    if usage.use_percent <= args.threshold:
        print(f"{usage.filesystem} usage is {usage.use_percent}%, below threshold {args.threshold}%.")
        return 0

    cfg = load_runtime_config()
    recipients = recipients_from_config(cfg, args.recipient_mode)
    subject_prefix = "[TEST] " if args.recipient_mode == "test" else ""
    subject = f"{subject_prefix}Jetson storage alert: {usage.filesystem} is {usage.use_percent}% full"
    body = build_alert_body(usage, args.threshold, args.device)

    EmailSender(cfg=cfg).send_text(subject, body, recipients=recipients)
    print(f"Email sent to {', '.join(recipients)} because {usage.filesystem} is {usage.use_percent}% full.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())