"""
Decides what to do about a purchase order that has not been marked delivered.
Pure function -- no DB, email or clock access -- so the rules are easy to test.

Returns "wait", "chase" (email the vendor) or "escalate" (alert a human).
"""

from datetime import datetime, timedelta


def next_delivery_action(delivery: dict, now: datetime, chase_interval_hours: int,
                         max_chases: int) -> str:
    if now.date() <= delivery["expected_delivery_date"]:
        return "wait"  # not late yet

    if delivery["escalated_at"] is not None:
        return "wait"  # a human already knows

    last = delivery["last_chased_at"]
    interval_passed = last is None or now - last >= timedelta(hours=chase_interval_hours)
    if not interval_passed:
        return "wait"

    return "chase" if delivery["chase_count"] < max_chases else "escalate"
