"""What to do about an invoice a person rejected while the supplier has not yet sent a corrected one.

Pure functions (no database, email or clock access), in the same spirit as the late-delivery rules:

  wait      nothing to do yet
  remind    email the supplier again (up to `max_chases` times, one `interval_hours` apart)
  alert     the supplier has had its reminders and still not answered: tell the Accounts team (once)
  escalate  Accounts was told long ago and nothing happened: tell the admin (once)
"""

from datetime import datetime, timedelta


def next_invoice_chase_action(rejected_at: datetime, chases: list[datetime], alerted_at: datetime | None, escalated: bool,
                              now: datetime, interval_hours: float, max_chases: int, escalate_hours: float,
                              can_email: bool = True) -> str:
    """`chases` are when the supplier was successfully reminded; `alerted_at` is when Accounts was told (or None);
    `can_email` is False when the supplier has no email address, so there is nobody to remind."""
    if escalated:
        return "wait"  # the admin already knows
    if alerted_at is not None:
        return "escalate" if escalate_hours > 0 and now - alerted_at >= timedelta(hours=escalate_hours) else "wait"

    reminders = len(chases) if can_email else max_chases  # no address: skip straight to telling a person
    last = max(chases) if chases else rejected_at
    if now - last < timedelta(hours=interval_hours):
        return "wait"
    return "remind" if reminders < max_chases else "alert"


def correction_overdue(rejected_at: datetime, now: datetime, interval_hours: float, max_chases: int) -> bool:
    """True once the supplier has had every reminder and a full interval after the last one: by now the schedule above
    has told Accounts, and the order is stuck until a person acts."""
    return now - rejected_at >= timedelta(hours=interval_hours * (max_chases + 1))
