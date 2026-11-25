"""Urgent requests: "needed by Friday". An urgent request is chased harder and weighed differently, never skipped.

  - suppliers get less time to quote (but never more than half the time left) and are reminded more often
  - approvers are reminded sooner and a stuck problem reaches the admin sooner
  - the ranking is told the date and each offer is marked as meeting it or not
  - an offer that cannot arrive in time is not approved automatically: a person decides

Pure functions: no database or clock.
"""

from datetime import date, datetime, timedelta

MIN_QUOTE_HOURS = 2.0
SHARE_OF_TIME_LEFT = 0.4          # suppliers get at most this share of the time left to quote


def resolve(form_needed_by: date | None, form_urgent: bool, ai_needed_by, ai_urgent, today: date, within_days: int) -> tuple[date | None, bool]:
    """The needed-by date and urgency of a new request. What the person typed in the form wins over what the AI read
    from the text. A date in the past or more than a year away is ignored (it is a misreading). A date within
    `within_days` makes the request urgent by itself."""
    needed = form_needed_by if form_needed_by is not None else _as_date(ai_needed_by)
    if needed is not None and not (today <= needed <= today + timedelta(days=365)):
        needed = None
    urgent = bool(form_urgent) or (form_needed_by is None and ai_urgent is True) or (needed is not None and (needed - today).days <= within_days)
    return needed, urgent


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def hours_left(needed_by: date | None, now: datetime) -> float | None:
    """Hours until the end of the needed-by day."""
    if needed_by is None:
        return None
    return (datetime.combine(needed_by, datetime.max.time()) - now).total_seconds() / 3600


def quote_deadline_hours(urgent: bool, needed_by: date | None, now: datetime, normal_hours: float, urgent_hours: float) -> float:
    """How long suppliers get to quote."""
    hours = urgent_hours if urgent else normal_hours
    left = hours_left(needed_by, now)
    if left is not None:
        hours = min(hours, max(MIN_QUOTE_HOURS, left * SHARE_OF_TIME_LEFT))
    return max(MIN_QUOTE_HOURS, hours)


def pick(urgent: bool, normal: float, when_urgent: float) -> float:
    """The shorter wait for an urgent request (never longer than the normal one)."""
    return min(normal, when_urgent) if urgent else normal


def meets(lead_time_days: int | None, needed_by: date | None, today: date) -> bool | None:
    """Can this supplier deliver by the date? None when we cannot tell (no date, or no delivery time quoted)."""
    if needed_by is None or lead_time_days is None:
        return None
    return today + timedelta(days=lead_time_days) <= needed_by


def request_note(urgent: bool, needed_by: date | None) -> str:
    """A line for the supplier, or nothing."""
    if not urgent and needed_by is None:
        return ""
    when = f" by {needed_by:%d %b %Y}" if needed_by else ""
    return (f"{'This is URGENT. ' if urgent else ''}We need delivery{when}. Please reply as soon as you can and say clearly whether you can "
            f"{'meet that date' if needed_by else 'deliver quickly'}.")


def ranking_note(needed_by: date | None, today: date) -> str:
    """Extra instruction for the ranking when there is a date."""
    if needed_by is None:
        return ""
    return (f" The goods are needed by {needed_by:%d %b %Y} (today is {today:%d %b %Y}). Each vendor has meets_needed_by: true, false or null "
            f"(null = unknown). A vendor who cannot deliver in time (false) must rank below every vendor who can, however cheap; "
            f"say so in its reason.")
