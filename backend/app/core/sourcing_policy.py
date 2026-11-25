"""
Decides what the worker should do next for a case that is waiting on vendor quotes.
Pure function -- no DB, email or clock access -- so the rules are easy to test.

Returns (action, rfq_ids):
  "rank"    -> enough has come in (everyone replied, or the deadline passed with >=1 quote)
  "stalled" -> nothing workable (no vendors invited, or deadline passed with no quotes): human needed
  "remind"  -> chase these silent vendors
  "wait"    -> nothing to do yet
"""

from datetime import datetime, timedelta


def next_sourcing_action(rfqs: list[dict], quote_count: int, now: datetime,
                         reminder_interval_hours: int, max_reminders: int) -> tuple[str, list[str]]:
    rfqs = [r for r in rfqs if r["status"] not in ("bounced", "withdrawn")]      # never reached, or taken back: nobody waits on them
    if not rfqs:
        return "stalled", []

    if all(r["status"] == "replied" for r in rfqs) and quote_count >= 1:
        return "rank", []

    if all(r["status"] == "replied" for r in rfqs):
        return "stalled", []                                  # everyone has answered and none gave a price (all refused): a person is needed now, not at the deadline

    if any(r["deadline_at"] <= now for r in rfqs):
        return ("rank", []) if quote_count >= 1 else ("stalled", [])

    interval = timedelta(hours=reminder_interval_hours)
    due = [
        r["rfq_id"] for r in rfqs
        if r["status"] != "replied"
        and r["reminder_count"] < max_reminders
        and now - r["last_contacted_at"] >= interval
    ]
    return ("remind", due) if due else ("wait", [])
