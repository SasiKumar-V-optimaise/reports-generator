"""Build standards-compliant email messages with file attachments."""

from email.message import EmailMessage
from pathlib import Path


class MessageBuilder:
    def build(
        self,
        subject: str,
        body: str,
        *,
        sender: str,
        recipients: tuple[str, ...],
        attachments: tuple[Path, ...] = (),
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(body)
        for attachment in attachments:
            message.add_attachment(
                attachment.read_bytes(),
                maintype="text",
                subtype="csv",
                filename=attachment.name,
            )
        return message
