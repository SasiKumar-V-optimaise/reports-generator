"""SMTP delivery with optional STARTTLS authentication."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage


class SmtpSender:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        username: str,
        password: str,
        use_starttls: bool = True,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_starttls = use_starttls
        self.timeout_seconds = timeout_seconds

    def send(self, message: EmailMessage) -> bool:
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as client:
            client.ehlo()
            if self.use_starttls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(self.username, self.password)
            client.send_message(message)
        return True
