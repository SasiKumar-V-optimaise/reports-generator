import subprocess
import time
from pathlib import Path

from reports.common.config_loader import load_runtime_config


class GDriveUploader:
    """
    Upload files to Google Drive using rclone.
    Uses:
      gdrive.remote
      gdrive.base_path
      gdrive.pipes_csv_dir
      gdrive.videos_dir
    """

    def __init__(self, cfg: dict | None = None, caster=None):
        cfg = cfg or load_runtime_config()
        gcfg = cfg["gdrive"]
        self.remote = gcfg["remote"]
        self.base_path = gcfg["base_path"].strip("/")

        self.pipes_csv_dir = gcfg.get("pipes_csv_dir", "Pipes_Data_Sheet").strip("/")
        self.videos_dir = gcfg.get("videos_dir", "Pipes_Data_Sheet/videos").strip("/")

    @staticmethod
    def _effective_timeout(timeout_seconds=None, deadline_monotonic=None):
        candidates = []
        if timeout_seconds is not None:
            timeout_seconds = float(timeout_seconds)
            if timeout_seconds <= 0:
                raise TimeoutError("rclone command deadline has already expired")
            candidates.append(timeout_seconds)
        if deadline_monotonic is not None:
            remaining = float(deadline_monotonic) - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("rclone command deadline has already expired")
            candidates.append(remaining)
        return min(candidates) if candidates else None

    def _run(self, args: list[str], *, timeout_seconds=None, deadline_monotonic=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=True,
            timeout=self._effective_timeout(timeout_seconds, deadline_monotonic),
        )

    def _mkdir(self, remote_dir: str, *, timeout_seconds=None, deadline_monotonic=None):
        # rclone mkdir is idempotent
        self._run(["rclone", "mkdir", remote_dir], timeout_seconds=timeout_seconds, deadline_monotonic=deadline_monotonic)

    def upload_csv(self, filepath: str, *, timeout_seconds=None, deadline_monotonic=None) -> str:
        return self._upload(
            filepath,
            f"{self.remote}:{self.base_path}/{self.pipes_csv_dir}",
            timeout_seconds=timeout_seconds,
            deadline_monotonic=deadline_monotonic,
        )

    def upload_video(self, filepath: str, *, timeout_seconds=None, deadline_monotonic=None) -> str:
        return self._upload(
            filepath,
            f"{self.remote}:{self.base_path}/{self.videos_dir}",
            timeout_seconds=timeout_seconds,
            deadline_monotonic=deadline_monotonic,
        )

    def _upload(self, filepath: str, target_dir: str, *, timeout_seconds=None, deadline_monotonic=None) -> str:
        file = Path(filepath).resolve()
        if not file.exists():
            raise FileNotFoundError(f"File not found: {file}")

        self._mkdir(target_dir, timeout_seconds=timeout_seconds, deadline_monotonic=deadline_monotonic)

        # copyto puts file exactly at target path
        target_file = f"{target_dir}/{file.name}"

        self._run(
            [
                "rclone", "copyto",
                str(file),
                target_file,
                "--drive-chunk-size", "128M",
            ],
            timeout_seconds=timeout_seconds,
            deadline_monotonic=deadline_monotonic,
        )

        # share link
        result = self._run(["rclone", "link", target_file], timeout_seconds=timeout_seconds, deadline_monotonic=deadline_monotonic)
        return result.stdout.strip()
