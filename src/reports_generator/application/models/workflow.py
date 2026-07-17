from dataclasses import dataclass
from datetime import date, datetime

from reports_generator.domain.shifts.models import Shift

from .artifact import StageResult


@dataclass(frozen=True, slots=True)
class WorkflowRequest:
    production_date: date
    shift: Shift
    caster_ids: tuple[str, ...] = ()
    test_mode: bool = False
    verified_only: bool = False


@dataclass(frozen=True, slots=True)
class CasterWorkflowResult:
    caster_id: str
    success: bool
    stages: tuple[StageResult, ...]


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    success: bool
    caster_results: tuple[CasterWorkflowResult, ...]
    started_at: datetime
    completed_at: datetime
    workflow_id: str = ""

    def to_dict(self):
        return {
            "workflow_id": self.workflow_id,
            "success": self.success,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "caster_results": [
                {
                    "caster_id": r.caster_id,
                    "success": r.success,
                    "stages": [
                        {
                            "stage": s.stage,
                            "success": s.success,
                            "warnings": list(s.warnings),
                            "errors": list(s.errors),
                            "artifacts": [
                                {
                                    "artifact_type": a.artifact_type.value,
                                    "caster_id": a.caster_id,
                                    "path": str(a.path),
                                }
                                for a in s.artifacts
                            ],
                        }
                        for s in r.stages
                    ],
                }
                for r in self.caster_results
            ],
        }
