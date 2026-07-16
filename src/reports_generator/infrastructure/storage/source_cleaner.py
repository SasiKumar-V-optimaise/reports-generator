from pathlib import Path


class SourceCleaner:
    def cleanup(self, path: Path):
        if path.exists() and path.is_file():
            path.unlink()


class GDriveUploader:
    def upload(self, artifacts):
        return True
