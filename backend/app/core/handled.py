"""What each team finished recently, for the "Recently handled" list under each My work queue.

Only things a PERSON did count (the agents' own work is not listed). Each is read from the case's events, so
nothing extra is stored. Pure functions: no database or clock.
"""

from datetime import datetime, timedelta

# event type -> (queue it belongs to, what happened, the payload field that says who did it)
HANDLED_EVENTS: dict[str, tuple[str, str, str]] = {
    "approval.approved": ("approval", "Approved", "decided_by"),
    "approval.rejected": ("approval", "Rejected", "decided_by"),
    "delivery.received": ("delivery", "Marked as received", "received_by"),
    "delivery.dispute_handled": ("delivery", "Followed up with the requester", "by"),
    "invoice.approved": ("invoice", "Invoice approved", "decided_by"),
    "invoice.rejected": ("invoice", "Invoice rejected", "decided_by"),
    "vendor.selected": ("vendor", "Chose a different supplier", "chosen_by"),
    "po.confirmed": ("po", "Recorded the supplier's confirmation", "by"),     # only when a person did it (by an email, "by" is empty)
    "po.problem_resolved": ("po", "Sorted out a problem with the order", "by"),
}

LIMIT_PER_QUEUE = 8


def recent_handled(events: list[dict], cases: dict[str, dict], now: datetime, hours: float, queue_keys: set[str]) -> dict[str, list[dict]]:
    """Newest first, per queue. `events` are {case_id, event_type, payload, created_at}; `cases` maps lower-case
    case id -> case. Only queues the person actually has are returned. An automatic event (nobody named) is skipped."""
    since = now - timedelta(hours=hours)
    out: dict[str, list[dict]] = {key: [] for key in queue_keys}
    for e in sorted(events, key=lambda e: e["created_at"], reverse=True):
        rule = HANDLED_EVENTS.get(e["event_type"])
        if rule is None or rule[0] not in queue_keys or e["created_at"] < since:
            continue
        by = (e.get("payload") or {}).get(rule[2])
        what = "Rejected, suppliers asked again" if e["event_type"] == "approval.rejected" and (e.get("payload") or {}).get("re_sourcing") else rule[1]
        if not by or len(out[rule[0]]) >= LIMIT_PER_QUEUE:
            continue
        case = cases.get(e["case_id"].lower())
        number, summary = (case or {}).get("case_number"), (case or {}).get("items_summary")
        out[rule[0]].append({
            "id": f"{e['event_type']}:{e['case_id'].lower()}:{e['created_at']:%Y%m%d%H%M%S%f}",
            "title": " · ".join(x for x in (number, summary) if x) or "A request",
            "what": what, "by": by, "at": e["created_at"], "link": f"/cases/{e['case_id']}",
        })
    return out
