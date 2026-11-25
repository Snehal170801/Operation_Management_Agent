"""Separation of duties: the people who do the risky steps of one order must be different people.

  - nobody approves a purchase that they asked for themselves
  - whoever confirmed the goods arrived cannot also decide that order's invoice
    (otherwise one person could "receive" goods that never came, and pay for them)

An admin may override, but only knowingly: the override is returned so the caller records it in the audit log.
Pure functions: no database access.
"""

from app.core.exceptions import RuleViolation


def _same(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()


def check_not_own_request(actor: str, requester: str | None, is_admin: bool) -> str | None:
    """Raises RuleViolation if `actor` is deciding their own request. Returns a note when an admin overrides."""
    if not _same(actor, requester):
        return None
    if is_admin:
        return "admin approved their own request"
    raise RuleViolation("You asked for this purchase, so someone else has to approve it.")


def check_not_the_receiver(actor: str, received_by: str | None, is_admin: bool) -> str | None:
    """Raises RuleViolation if `actor` confirmed the goods for this order and is now deciding its invoice."""
    if not _same(actor, received_by):
        return None
    if is_admin:
        return "admin decided an invoice for goods they confirmed"
    raise RuleViolation("You confirmed the goods for this order, so someone else has to decide its invoice.")
