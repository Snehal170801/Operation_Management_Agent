"""Quotes expire ("valid for 7 days"). An approval that waited longer must not order at a price the supplier no longer stands behind.

Pure functions: no database or clock.
"""

from datetime import datetime, timedelta

MAX_VALID_DAYS = 365


def valid_until(created_at: datetime, valid_days) -> datetime | None:
    """When a quote stops being valid, from the number of days the supplier said it stays valid (None if not stated or absurd)."""
    if isinstance(valid_days, bool) or not isinstance(valid_days, (int, float)) or valid_days != valid_days:
        return None
    days = int(valid_days)
    return created_at + timedelta(days=days) if 1 <= days <= MAX_VALID_DAYS else None


def is_expired(quote: dict, now: datetime) -> bool:
    until = quote.get("valid_until")
    return until is not None and until < now


def tag(quote: dict, now: datetime) -> str | None:
    """A short label for the approver: "Quote expired" or "Valid until 12 Oct", or nothing when no validity was stated."""
    until = quote.get("valid_until")
    if until is None:
        return None
    return "Quote expired" if until < now else f"Valid until {until:%d %b}"
