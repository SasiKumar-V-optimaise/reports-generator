from datetime import date
from types import SimpleNamespace

from reports_generator.application.models import (
    Artifact,
    ArtifactType,
    StageResult,
    WorkflowRequest,
)
from reports_generator.application.services.local_workflow import LocalNotificationService
from reports_generator.domain.shifts import Shift
from reports_generator.infrastructure.config.models import EmailConfig


class _CapturingSender:
    def __init__(self) -> None:
        self.messages = []

    def send(self, message) -> bool:
        self.messages.append(message)
        return True


def test_verified_notification_attaches_csv_for_verified_recipients(tmp_path) -> None:
    verified_path = tmp_path / "17-07-2026_shift_A_verified.csv"
    verified_path.write_text("pipe_number,pipe_uid\n1,42\n", encoding="utf-8")
    email = EmailConfig(
        smtp_host="smtp.example.test",
        smtp_port=587,
        sender="reports@example.test",
        password_env="EMAIL_APP_PASSWORD",
        recipients=("general@example.test",),
        verified_recipients=("verified@example.test",),
    )
    config = SimpleNamespace(
        email=email,
        caster=lambda _caster_id: SimpleNamespace(display_name="Caster 2"),
    )
    request = WorkflowRequest(
        production_date=date(2026, 7, 17),
        shift=Shift.A,
        caster_ids=("caster2",),
        verified_only=True,
    )
    report = StageResult(
        "report",
        True,
        artifacts=(Artifact(ArtifactType.VERIFIED_CSV, "caster2", verified_path),),
    )
    context = SimpleNamespace(request=request, caster_id="caster2", stages=[report])
    sender = _CapturingSender()

    result = LocalNotificationService(config, sender=sender).notify(context)

    assert result.success
    assert len(sender.messages) == 1
    message = sender.messages[0]
    assert message["To"] == "verified@example.test"
    assert "Caster 2" in message["Subject"]
    attachment = next(message.iter_attachments())
    assert attachment.get_filename() == verified_path.name
    assert attachment.get_payload(decode=True) == verified_path.read_bytes()
