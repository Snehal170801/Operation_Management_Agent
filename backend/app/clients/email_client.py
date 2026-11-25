import logging
import smtplib
import socket
from email.message import EmailMessage

from app.core.config import settings
from app.core.retry import retry

# Added to every email we send. The mailbox reader skips messages carrying it, so when the sending
# and reading mailbox are the same (or a supplier's address forwards back to it) the system does not
# read its own quote requests and purchase orders as replies.
OUTBOUND_HEADER = "X-OA-Outbound"

logger = logging.getLogger(__name__)


def is_passing_mail_problem(exc: BaseException) -> bool:
    if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError)):
        return isinstance(exc, smtplib.SMTPDataError) and 400 <= exc.smtp_code < 500   # 4xx = "try later"; 5xx = refused for good
    return isinstance(exc, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, socket.timeout, TimeoutError, ConnectionError, smtplib.SMTPHeloError))


def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    """Send an email (plain text, plus an HTML version when `html` is given). Raises on failure. Without SMTP_HOST it only logs (dry run)."""
    if settings.TEST_MAIL_DIR:                      # automated tests only (refused unless a *_test database): write to a folder, send nothing
        from app.clients import test_mailbox
        test_mailbox.write_outbox(settings.TEST_MAIL_DIR, to, subject, body, html)
        return
    if not settings.SMTP_HOST:
        logger.info("[email dry-run] to=%s subject=%s\n%s", to, subject, body)
        return

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM or settings.SMTP_USER
    message["To"] = to
    message["Subject"] = subject
    message[OUTBOUND_HEADER] = "1"
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")

    def deliver() -> None:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)

    # A dropped connection or a busy server is tried again (twice); a wrong password or a refused address is not.
    retry(deliver, attempts=3, delay=1.0, transient=is_passing_mail_problem, what="Sending email")
