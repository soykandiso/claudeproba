"""Sending mail (roadmap P3 s44): one function, two ways out.

**outbox** writes each message as an `.eml` file to `settings.outbox_dir` and logs the
path: development and tests read sign-in links there, and nothing leaves the machine.
**smtp** sends through the provider configured in the environment. Production uses
nothing else, and refuses to send until the host is set: a domain to send from is
docs/decisions.md D2, still open, and a sign-in link from an unconfigured server would
land in spam or nowhere.

Plain text only. A sign-in mail is a sentence and a link, a proforma's is a sentence and a
PDF (P4 s50); HTML adds a tracking surface and a rendering problem for no gain.
"""

import datetime as dt
import logging
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from app.config import Settings

log = logging.getLogger(__name__)


class MailNotConfigured(RuntimeError):
    """Production has no SMTP host: nothing is sent, and the caller says so."""


def send(
    settings: Settings,
    to: str,
    subject: str,
    body: str,
    attachments: tuple[tuple[str, bytes, str], ...] = (),
) -> str:
    """Send one plain-text message, with (filename, bytes, type) attachments; its Message-ID."""
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=_domain(settings.mail_from))
    message.set_content(body)
    for filename, data, mimetype in attachments:
        maintype, subtype = mimetype.split("/", 1)
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    if settings.mail_backend == "outbox" and not settings.is_production:
        folder = Path(settings.outbox_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S")
        path = folder / f"{stamp}-{uuid.uuid4().hex[:8]}.eml"
        path.write_bytes(bytes(message))
        log.info("mail to the outbox: %s", path)
        return message["Message-ID"]

    if not settings.smtp_host:
        raise MailNotConfigured("no SMTP host: set GRANTS_SMTP_HOST (docs/decisions.md D2)")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(message)
    return message["Message-ID"]


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip(" >") or "localhost"
