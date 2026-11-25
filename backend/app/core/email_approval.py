"""Deciding from the email in one tap: when a link may be offered, and whether a link can still be used.

A link is made for one person and one approval. Opening it only SHOWS the order (email scanners and previews open links, so
that must change nothing); the decision itself needs a confirming tap on the page. A link works once, expires, and stops working
as soon as the approval is decided any other way. Larger orders are never offered a link: they are decided in the app.

Pure functions: no database or clock.
"""

from datetime import datetime, timedelta

APPROVE, REFUSE = "approve", "refuse"
ACTIONS = (APPROVE, REFUSE)

# What the page says for each reason a link cannot be used. Deliberately short and the same for every cause of "not valid",
# so a stranger who guesses a link learns nothing.
MESSAGES = {
    "invalid": "This link is not valid.",
    "used": "This link has already been used.",
    "expired": "This link has expired. Please open the app to decide.",
    "revoked": "This link is no longer needed: a newer email replaced it, or the order was decided another way.",
    "decided": "This order has already been decided.",
    "person": "This link was sent to someone who can no longer approve orders.",
}


def offer_link(enabled: bool, amount: float | None, max_amount: float, kind: str) -> bool:
    """Whether the email should carry Approve/Refuse buttons. Not for orders above the limit, nor when the amount is
    unknown (a person should look at those in the app), and never when the feature is switched off."""
    if not enabled or max_amount <= 0:
        return False
    if kind == "price_change":
        return amount is not None and amount <= max_amount      # a higher price is money too: same limit, on the new total
    return amount is not None and amount <= max_amount


def expires_at(now: datetime, hours: float) -> datetime:
    return now + timedelta(hours=max(1.0, hours))


def link_problem(link: dict | None, now: datetime) -> str | None:
    """None if the link can be used, otherwise the key of the message to show (see MESSAGES)."""
    if link is None:
        return "invalid"
    if link.get("used_at") is not None:
        return "used"
    if link.get("revoked_at") is not None:
        return "revoked"
    if link["expires_at"] < now:
        return "expired"
    return None


def action_from(value: str | None) -> str | None:
    return value if value in ACTIONS else None


def describe_decision(action: str, username: str) -> str:
    return f"{'Approved' if action == APPROVE else 'Refused'} by {username} from the email link"
