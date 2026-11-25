"""When to chase a supplier who has not confirmed a purchase order, and when to tell a person.

Pure function: no database, email or clock access, so the rules are easy to test.

  "wait"      nothing to do (confirmed, a person already knows, or it is not time yet)
  "chase"     ask the supplier again to confirm
  "escalate"  chased enough with no answer: alert the PO team once
"""

from datetime import datetime, timedelta


def next_confirm_action(po: dict, now: datetime, interval_hours: float, max_chases: int) -> str:
    if po.get("acknowledged_at") is not None:
        return "wait"                                   # confirmed
    if po.get("confirm_escalated_at") is not None or po.get("vendor_issue"):
        return "wait"                                   # a person already has it
    if po.get("sent_at") is None:
        return "wait"                                   # not emailed yet, so nothing to confirm

    last = po.get("last_confirm_chase_at") or po["sent_at"]
    if now - last < timedelta(hours=interval_hours):
        return "wait"
    return "chase" if (po.get("confirm_chase_count") or 0) < max_chases else "escalate"
