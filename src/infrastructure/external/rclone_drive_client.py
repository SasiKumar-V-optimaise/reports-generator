import subprocess
from pathlib import Path

from src.infrastructure.config.runtime_config_loader import load_runtime_config


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

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, check=True)

    def _mkdir(self, remote_dir: str):
        # rclone mkdir is idempotent
        self._run(["rclone", "mkdir", remote_dir])

    def upload_csv(self, filepath: str) -> str:
        return self._upload(filepath, f"{self.remote}:{self.base_path}/{self.pipes_csv_dir}")

    def upload_video(self, filepath: str) -> str:
        return self._upload(filepath, f"{self.remote}:{self.base_path}/{self.videos_dir}")

    def _upload(self, filepath: str, target_dir: str) -> str:
        file = Path(filepath).resolve()
        if not file.exists():
            raise FileNotFoundError(f"File not found: {file}")

        self._mkdir(target_dir)

        # copyto puts file exactly at target path
        target_file = f"{target_dir}/{file.name}"

        self._run([
            "rclone", "copyto",
            str(file),
            target_file,
            "--drive-chunk-size", "128M",
        ])

        # share link
        result = self._run(["rclone", "link", target_file])
        return result.stdout.strip()


