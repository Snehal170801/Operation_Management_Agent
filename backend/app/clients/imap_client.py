import base64
import email
import email.header
import imaplib
import logging
import re
import select
import time
from email.message import Message
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Callable

from app.core import attachments as attachment_reader
from app.core.config import settings
from app.clients.email_client import OUTBOUND_HEADER
from app.core.email_parsing import REF_PREFIX

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 60  # a half-dead connection must fail, not hang the worker forever


def process_unseen_replies(handler: Callable[[dict], None], senders: tuple[str, ...] = ()) -> int:
    """Call handler({from_email, subject, body, attachments}) for each unread email tagged with our
    case reference, then mark it read. A message is marked read even if the handler fails,
    so one bad email is never reprocessed (each reprocess could cost an LLM call).
    Returns how many messages were handled. No-op when IMAP is not configured."""
    if settings.TEST_MAIL_DIR:                      # automated tests only: read the test inbox folder instead of IMAP
        from app.clients import test_mailbox
        return test_mailbox.process_unseen(settings.TEST_MAIL_DIR, handler, senders)
    if not settings.IMAP_HOST:
        return 0

    handled = 0
    with imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT, timeout=CONNECT_TIMEOUT_SECONDS) as imap:
        imap.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
        imap.select(settings.IMAP_FOLDER)
        ids: list[bytes] = []
        # Our case tag in the subject, a bounce from the mail system, or any mail from a supplier we know (a document sent as a fresh email, with no tag)
        for criteria in (("SUBJECT", f'"{REF_PREFIX}"'), ("FROM", '"mailer-daemon"'), ("FROM", '"postmaster"'), *(("FROM", f'"{a}"') for a in senders if a and '"' not in a)):
            _, data = imap.search(None, "UNSEEN", *criteria)         # (a bounce's subject does not carry our tag; its sender is the mail system)
            ids += [i for i in data[0].split() if i not in ids]
        for msg_id in ids:
            try:
                _, fetched = imap.fetch(msg_id, "(BODY.PEEK[])")
                handler(parse_message(email.message_from_bytes(fetched[0][1])))
                handled += 1
            except Exception:
                logger.exception("Failed to process inbound email %s", msg_id)
            finally:
                imap.store(msg_id, "+FLAGS", "\\Seen")
    return handled


def wait_for_new_mail(timeout: int) -> bool:
    """Block until the mail server says new mail arrived in the folder (IMAP IDLE), or `timeout` seconds pass.
    True means "something arrived, go and read". False means nothing came, or the connection dropped; the
    caller simply asks again. Opens its own short-lived connection, so it never disturbs a normal read.
    No-op (False) when IMAP is not configured."""
    if settings.TEST_MAIL_DIR:
        from app.clients import test_mailbox
        return test_mailbox.wait_for_new(settings.TEST_MAIL_DIR, timeout)
    if not settings.IMAP_HOST:
        return False
    imap = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT, timeout=CONNECT_TIMEOUT_SECONDS)
    try:
        imap.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
        imap.select(settings.IMAP_FOLDER, readonly=True)
        tag = imap._new_tag()
        imap.send(tag + b" IDLE\r\n")
        if not imap.readline().startswith(b"+"):
            return False  # the server does not do IDLE: the once-a-minute read still covers us
        deadline = time.monotonic() + timeout
        sock = imap.sock
        while time.monotonic() < deadline:
            # wake every few seconds to check the clock; an SSL socket may already hold bytes select() can't see
            if not (sock.pending() or select.select([sock], [], [], 5)[0]):
                continue
            line = imap.readline()
            if b"EXISTS" in line:
                return True
        return False
    except Exception:
        logger.warning("Waiting for new mail failed (will retry)", exc_info=True)
        return False
    finally:
        try:
            imap.send(b"DONE\r\n")
        except Exception:
            pass
        try:
            imap.shutdown()
        except Exception:
            pass


def parse_message(message: Message) -> dict:
    """The parts of an email the pipeline needs. `attachments` is [{"name", "text"}], where text is
    None when the file could not be read (scanned PDF, unsupported type, too big...)."""
    return {
        "from_email": parseaddr(message.get("From", ""))[1].lower(),
        "subject": _decode_header(message),
        "body": _body_text(message),
        "attachments": _attachments(message),
        # True for mail this system sent itself (see email_client.OUTBOUND_HEADER)
        "outbound": message.get(OUTBOUND_HEADER) == "1",
    }


def _decode_header(message: Message) -> str:
    return str(email.header.make_header(email.header.decode_header(message.get("Subject", ""))))


def _body_text(message: Message) -> str:
    """The written part of the email: plain text if there is any, otherwise the HTML with tags removed."""
    parts = list(message.walk()) if message.is_multipart() else [message]
    for wanted in ("text/plain", "text/html"):
        for part in parts:
            if part.get_content_type() == wanted and not part.get_filename():
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                text = _html_to_text(text) if wanted == "text/html" else text
                if text.strip():
                    return text
    return ""


def _attachments(message: Message) -> list[dict]:
    found = []
    for part in message.walk():
        name = part.get_filename()
        if not name:
            continue
        name = str(email.header.make_header(email.header.decode_header(name)))
        data = part.get_payload(decode=True) or b""
        text = attachment_reader.extract_text(name, data)
        entry = {"name": name, "text": text}
        if settings.PDF_VISION_ENABLED and not (text or "").strip():          # a scan or a photo: keep page pictures for the AI to look at
            pictures = attachment_reader.page_images(name, data, settings.PDF_VISION_MAX_PAGES)
            if pictures:
                entry["images"] = [base64.b64encode(p).decode("ascii") for p in pictures]
        found.append(entry)
    return found


class _TextOnly(HTMLParser):
    """Turns HTML into readable text: line breaks for block tags, cells separated, scripts/styles dropped."""

    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in ("td", "th"):
            self.chunks.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    return re.sub(r"\n\s*\n+", "\n", "".join(parser.chunks)).strip()
