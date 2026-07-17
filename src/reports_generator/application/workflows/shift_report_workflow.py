from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from reports_generator.application.models import *
from reports_generator.application.services import *
from reports_generator.infrastructure.config.models import AppConfig


@dataclass
class _Context:
    request: WorkflowRequest
    caster_id: str
    stages: list[StageResult] = field(default_factory=list)

    @property
    def full_video_ok(self):
        return any(
            s.stage == "video"
            and s.success
            and any(a.artifact_type is ArtifactType.VIDEO for a in s.artifacts)
            for s in self.stages
        ) or any(s.stage == "video" and s.success for s in self.stages)


class ShiftReportWorkflow:
    def __init__(
        self,
        config: AppConfig,
        report_service=None,
        video_service=None,
        upload_service=None,
        notification_service=None,
        cleanup_service=None,
        state_store=None,
    ):
        self.config = config
        self.report_service = report_service or ReportService()
        self.video_service = video_service or VideoService()
        self.upload_service = upload_service or UploadService()
        self.notification_service = notification_service or NotificationService()
        self.cleanup_service = cleanup_service or CleanupService()
        self.state_store = state_store

    def run(self, request: WorkflowRequest) -> WorkflowResult:
        started = datetime.now(timezone.utc)
        ids = request.caster_ids or tuple(c.id for c in self.config.active_casters)
        results = []
        for cid in ids:
            ctx = _Context(request, cid)
            stages = (
                (
                    ("report", self.report_service.generate),
                    ("notification", self.notification_service.notify),
                )
                if request.verified_only
                else (
                    ("report", self.report_service.generate),
                    ("video", self.video_service.generate),
                    ("upload", self.upload_service.upload),
                    ("notification", self.notification_service.notify),
                )
            )
            for stage, method in stages:
                try:
                    ctx.stages.append(method(ctx))
                except Exception as exc:
                    ctx.stages.append(StageResult(stage, False, errors=(str(exc),)))
            if not request.verified_only and ctx.full_video_ok:
                try:
                    ctx.stages.append(self.cleanup_service.cleanup(ctx))
                except Exception as exc:
                    ctx.stages.append(StageResult("cleanup", False, errors=(str(exc),)))
            results.append(
                CasterWorkflowResult(cid, all(s.success for s in ctx.stages), tuple(ctx.stages))
            )
        out = WorkflowResult(
            all(r.success for r in results),
            tuple(results),
            started,
            datetime.now(timezone.utc),
            workflow_id=f"{request.production_date.isoformat()}_{request.shift.value}",
        )
        if not request.verified_only and self.state_store and hasattr(self.state_store, "save"):
            self.state_store.save(out)
        return out


class GateReportWorkflow(ShiftReportWorkflow):
    pass
