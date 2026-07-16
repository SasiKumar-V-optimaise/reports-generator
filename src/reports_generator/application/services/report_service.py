from __future__ import annotations

from typing import Any, Protocol

from reports_generator.application.models import *


class _Svc(Protocol):
    def generate(self, context: Any) -> StageResult: ...


class ReportService:
    def __init__(self, generator=None):
        self.generator = generator

    def generate(self, context):
        if self.generator:
            return _coerce(self.generator(context), "report")
        return StageResult(
            "report", False, warnings=("report generation skipped: no reader/writer configured",)
        )


class VideoService:
    def __init__(self, generator=None):
        self.generator = generator

    def generate(self, context):
        if self.generator:
            return _coerce(self.generator(context), "video")
        return StageResult(
            "video", False, warnings=("video generation skipped: no generator configured",)
        )


class UploadService:
    def __init__(self, uploader=None):
        self.uploader = uploader

    def upload(self, context):
        if self.uploader:
            return _coerce(self.uploader(context), "upload")
        return StageResult("upload", True)


class NotificationService:
    def __init__(self, notifier=None):
        self.notifier = notifier

    def notify(self, context):
        if self.notifier:
            return _coerce(self.notifier(context), "notification")
        return StageResult("notification", True)


class CleanupService:
    def __init__(self, cleaner=None):
        self.cleaner = cleaner

    def cleanup(self, context):
        if self.cleaner:
            return _coerce(self.cleaner(context), "cleanup")
        return StageResult("cleanup", True)


def _coerce(value, stage):
    return value if isinstance(value, StageResult) else StageResult(stage, bool(value is not False))
