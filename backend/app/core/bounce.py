"""Bounced emails: the mail server says "this address does not work". Wait no longer for a supplier we cannot reach.

A bounce arrives in our own mailbox from the mail system (mailer-daemon, postmaster). We read it to learn WHICH address failed,
WHICH request it was about (when the original subject is quoted) and WHETHER it is permanent (no such address) or only
temporary (mailbox full, try later: ignored, the supplier is simply not reachable yet).

Pure functions over {from_email, subject, body}: no database or clock.
"""

import re

from app.core.email_parsing import parse_case_ref

_SENDERS = re.compile(r"(mailer-daemon|postmaster|mail delivery subsystem|mail delivery system|mailerdaemon)", re.I)
_SUBJECTS = re.compile(r"(delivery status notification|undeliverable|undelivered mail|returned mail|mail delivery failed|"
                       r"delivery failure|failure notice|could not be delivered|non-delivery|nondelivery)", re.I)
_ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_FOUND = (
    re.compile(r"Final-Recipient:\s*rfc822;\s*(\S+)", re.I),
    re.compile(r"wasn'?t delivered to\s+(\S+)", re.I),
    re.compile(r"delivery to the following recipients? failed[^\n]*\n+\s*(\S+)", re.I),
    re.compile(r"couldn'?t be delivered to\s+(\S+)", re.I),
    re.compile(r"^\s*<?([^\s<>]+@[^\s<>]+)>?:\s+(?:host|550|553|554|user|the email|recipient)", re.I | re.M),
    re.compile(r"Original-Recipient:\s*rfc822;\s*(\S+)", re.I),
)
_PERMANENT = re.compile(r"(address not found|does not exist|doesn'?t exist|no such user|unknown user|user unknown|recipient (?:rejected|not found)|"
                        r"invalid (?:recipient|address)|\b5\.[0-9]\.[0-9]\b|\b55[0-9]\b|mailbox (?:unavailable|not found|disabled)|"
                        r"domain (?:not found|does not exist)|couldn'?t be found|unable to receive mail)", re.I)
_TEMPORARY = re.compile(r"(mailbox (?:is )?full|over quota|try again later|temporarily|\b4\.[0-9]\.[0-9]\b|\b45[0-9]\b|greylist|deferred)", re.I)


def is_bounce(message: dict) -> bool:
    """Mail from the mail system itself reporting a failed delivery (not a person's reply, not an out-of-office)."""
    if _SENDERS.search(message.get("from_email") or ""):
        return True
    body = message.get("body") or ""
    return bool(_SUBJECTS.search(message.get("subject") or "")) and any(p.search(body) for p in _FOUND[:4])


def _clean(address: str) -> str:
    return address.strip().strip("<>()[]\"',;:.").lower()


def parse(message: dict) -> dict:
    """{"address", "case_id", "reason", "permanent", "about"}: the failed address (None if it cannot be found), the request the
    original email was about (None if not quoted), a short reason, whether it is permanent, and what we had sent ("order" or "quote")."""
    text = f"{message.get('subject') or ''}\n{message.get('body') or ''}"
    address = None
    for pattern in _FOUND:
        found = pattern.search(text)
        if found and _ADDRESS.search(found.group(1)):
            address = _clean(_ADDRESS.search(found.group(1)).group(0))
            break
    reason = "The email could not be delivered."
    for line in (message.get("body") or "").splitlines():
        stripped = line.strip()
        if stripped and (_PERMANENT.search(stripped) or _TEMPORARY.search(stripped)) and len(stripped) < 220:
            reason = stripped
            break
    permanent = bool(_PERMANENT.search(text)) and not _TEMPORARY.search(text)       # unsure means "temporary": better to wait than to give up on a supplier
    lower = text.lower()
    about = "order" if ("purchase order" in lower or "- cancellation" in lower or "goods problem" in lower) else "quote" if "quotation" in lower or "request for quotation" in lower else None
    return {"address": address, "case_id": parse_case_ref(text), "reason": reason[:300], "permanent": permanent, "about": about}
