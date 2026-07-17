from pathlib import Path

from reports_generator.application.services.local_workflow import (
    LocalCleanupService,
    LocalNotificationService,
    LocalReportService,
    LocalUploadService,
    LocalVideoService,
)
from reports_generator.application.workflows.shift_report_workflow import ShiftReportWorkflow
from reports_generator.infrastructure.config.loader import load_config
from reports_generator.infrastructure.storage.state_store import JsonStateStore
from reports_generator.shared.paths import OutputPathBuilder


def create_application(project_root: Path | None = None, caster_ids=()):
    root = project_root or Path.cwd()
    config = load_config(root, selected_caster_ids=caster_ids)
    paths = OutputPathBuilder(config.paths.output_root)
    paths.create_for_casters(c.id for c in config.active_casters)
    workflow = ShiftReportWorkflow(
        config,
        report_service=LocalReportService(config, paths),
        video_service=LocalVideoService(config, paths),
        upload_service=LocalUploadService(),
        notification_service=LocalNotificationService(config),
        cleanup_service=LocalCleanupService(),
        state_store=JsonStateStore(config.paths.state_root),
    )
    return config, workflow
