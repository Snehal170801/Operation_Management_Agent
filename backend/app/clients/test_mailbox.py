"""A folder that stands in for the mailbox, for automated end-to-end tests only (see core/test_switches.py for the safety guard).

    <dir>/outbox/*.json     every email the app "sent": {to, subject, body, html, sent_at}
    <dir>/inbox/*.json      mail "arriving" for the app: {from_email, subject, body, attachments?}  (or a raw .eml)
    <dir>/inbox/processed/  mail the app has already read

A test drops a supplier's reply into inbox (usually with reply_to); the app's mailbox reader picks it up exactly as it would an unread IMAP message.
"""

import email
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.email_parsing import REF_PREFIX


def _dir(base: str, name: str) -> Path:
    path = Path(base) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(folder: Path, data: dict) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    target = folder / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)                      # a reader never sees a half-written file
    return target


# ---- what the app sends
def write_outbox(base: str, to: str, subject: str, body: str, html: str | None = None) -> Path:
    return _write_json(_dir(base, "outbox"), {"to": to, "subject": subject, "body": body, "html": html,
                                              "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def read_outbox(base: str, to: str | None = None, subject_contains: str | None = None) -> list[dict]:
    """Emails sent so far, oldest first, optionally only those to an address or whose subject contains some text."""
    found = []
    for path in sorted(_dir(base, "outbox").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if to and entry["to"].lower() != to.lower():
            continue
        if subject_contains and subject_contains.lower() not in entry["subject"].lower():
            continue
        found.append(entry)
    return found


# ---- what arrives for the app
def drop_inbound(base: str, from_email: str, subject: str, body: str, attachments: list[dict] | None = None) -> Path:
    return _write_json(_dir(base, "inbox"), {"from_email": from_email, "subject": subject, "body": body, "attachments": attachments or []})


def reply_to(base: str, sent: dict, body: str, from_email: str | None = None) -> Path:
    """A supplier answering an email the app sent: same subject (it carries the case tag), from the address it was sent to."""
    subject = sent["subject"] if sent["subject"].lower().startswith("re:") else "Re: " + sent["subject"]
    return drop_inbound(base, from_email or sent["to"], subject, body)


def _message(path: Path) -> dict:
    if path.suffix == ".eml":
        from app.clients.imap_client import parse_message
        return parse_message(email.message_from_bytes(path.read_bytes()))
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"from_email": (data.get("from_email") or "").lower(), "subject": data.get("subject", ""), "body": data.get("body", ""),
            "attachments": data.get("attachments") or [], "outbound": bool(data.get("outbound", False))}


def _wanted(message: dict, senders: tuple[str, ...] = ()) -> bool:
    """The same filter the real mailbox reader applies: our case tag in the subject, or a bounce from the mail system."""
    sender = message["from_email"]
    return REF_PREFIX in message["subject"] or "mailer-daemon" in sender or "postmaster" in sender or sender in {s.lower() for s in senders}


def _pending(base: str) -> list[Path]:
    inbox = _dir(base, "inbox")
    return sorted(p for p in inbox.iterdir() if p.is_file() and p.suffix in (".json", ".eml"))


def has_unseen(base: str) -> bool:
    return bool(_pending(base))


def process_unseen(base: str, handler, senders: tuple[str, ...] = ()) -> int:
    """Hand each waiting message to `handler` and move it to processed (even if the handler fails, like the real reader).
    Returns how many were handled."""
    done = _dir(base, "inbox/processed")
    handled = 0
    for path in _pending(base):
        try:
            message = _message(path)
            if _wanted(message, senders):
                handler(message)
                handled += 1
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to process test inbox message %s", path.name)
        finally:
            path.replace(done / path.name)
    return handled


def wait_for_new(base: str, timeout: int) -> bool:
    """True as soon as something is waiting in the inbox, False after `timeout` seconds of nothing."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if has_unseen(base):
            return True
        time.sleep(0.5)
    return False
