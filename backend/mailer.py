"""Outbound mail for password-reset codes: Brevo in production, in-memory in tests, log in dev."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Protocol

from flask import current_app

from backend.config import Settings

LOG = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_TIMEOUT_S = 10
RESET_SUBJECT = "Your PiyaNota reset code"
_HTTP_OK_MIN = 200
_HTTP_OK_MAX = 300


class MailError(Exception):
    """Mail could not be sent. The message never contains the recipient address."""


class Mailer(Protocol):
    def send_reset_code(self, to: str, code: str) -> None:
        """Deliver ``code`` to ``to`` or raise MailError."""


class MemoryMailer:
    """Test double: records (recipient, code) pairs instead of sending."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_reset_code(self, to: str, code: str) -> None:
        self.sent.append((to, code))


class LogMailer:
    """Dev only: logs the code so a developer can complete a reset without a mail account."""

    def send_reset_code(self, to: str, code: str) -> None:
        LOG.warning("DEV mail backend: reset code for %s is %s", to, code)


class BrevoMailer:
    """Sends through Brevo's transactional API using only the standard library."""

    def __init__(
        self, api_key: str, sender_email: str, sender_name: str, ttl_minutes: int
    ) -> None:
        self._api_key = api_key
        self._ttl_minutes = ttl_minutes
        self._sender = {"email": sender_email, "name": sender_name}

    def send_reset_code(self, to: str, code: str) -> None:
        payload = {
            "sender": self._sender,
            "to": [{"email": to}],
            "subject": RESET_SUBJECT,
            "textContent": (
                f"Your PiyaNota password reset code is {code}. "
                f"It expires in {self._ttl_minutes} minutes."
            ),
        }
        req = urllib.request.Request(
            BREVO_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"api-key": self._api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=BREVO_TIMEOUT_S) as resp:
                status = resp.status
        except urllib.error.HTTPError as exc:
            exc.close()
            raise MailError(f"Brevo rejected the message (HTTP {exc.code})") from None
        except (urllib.error.URLError, OSError) as exc:
            # type only: URLError text can echo the request URL or host details.
            raise MailError(f"Brevo unreachable ({type(exc).__name__})") from None
        if not _HTTP_OK_MIN <= status < _HTTP_OK_MAX:
            raise MailError(f"Brevo rejected the message (HTTP {status})")


def build_mailer(cfg: Settings) -> Mailer:
    """Pick the implementation named by ``cfg.mail_backend``."""
    if cfg.mail_backend == "brevo":
        return BrevoMailer(
            cfg.brevo_api_key, cfg.mail_from, cfg.mail_from_name, cfg.reset_code_ttl_minutes
        )
    if cfg.mail_backend == "log":
        return LogMailer()
    return MemoryMailer()


def get_mailer() -> Mailer:
    """The mailer registered on the current app."""
    mailer: Mailer = current_app.extensions["mailer"]
    return mailer
