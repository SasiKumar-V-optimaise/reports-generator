from pathlib import Path

from reports_generator.application.workflows.shift_report_workflow import ShiftReportWorkflow
from reports_generator.infrastructure.config.loader import load_config
from reports_generator.shared.paths import OutputPathBuilder


def create_application(project_root: Path | None = None, caster_ids=()):
    root = project_root or Path.cwd()
    config = load_config(root, selected_caster_ids=caster_ids)
    OutputPathBuilder(config.paths.output_root).create_for_casters(
        c.id for c in config.active_casters
    )
    return config, ShiftReportWorkflow(config)
