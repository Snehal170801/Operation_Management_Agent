"""When a department has had a problem sitting too long, a senior person is told: nobody gets to ignore an alert forever.

Pure function: it only decides WHAT is overdue. Telling the admin, and remembering that it was told (so it is
told once, not on every tick), is the pipeline's job.
"""

from datetime import datetime, timedelta

# stage -> (kind of problem, what to say)
STUCK_STAGES = {
    "sourcing_stalled": "No supplier has replied with a quote",
    "po_send_failed": "A purchase order could not be emailed",
    "po_failed": "A purchase order could not be created",
    "delivery_late": "A delivery is overdue",
}


def due_escalations(now: datetime, hours: float, approvals: list[dict], cases: list[dict], invoices: list[dict],
                    already: set[tuple[str, str]], urgent_cases: set[str] | frozenset = frozenset(),
                    urgent_hours: float | None = None) -> list[dict]:
    """Everything that has waited longer than `hours` and has not been escalated yet. `already` holds
    (kind, ref) pairs that were escalated before. Each result: kind, ref, case_id, case_number, what, hours_waiting."""
    if hours <= 0:
        return []
    cutoff = now - timedelta(hours=hours)
    urgent_cutoff = now - timedelta(hours=min(hours, urgent_hours)) if urgent_hours else cutoff       # (an urgent case waits less)
    by_id = {c["case_id"].lower(): c for c in cases}
    found: list[dict] = []

    def add(kind: str, ref: str, case_id: str, what: str, since: datetime) -> None:
        if since > (urgent_cutoff if case_id.lower() in urgent_cases else cutoff) or (kind, ref.lower()) in already:
            return
        case = by_id.get(case_id.lower()) or {}
        found.append({"kind": kind, "ref": ref.lower(), "case_id": case_id, "case_number": case.get("case_number"),
                      "summary": case.get("items_summary"), "what": what,
                      "hours_waiting": round((now - since).total_seconds() / 3600, 1)})

    for a in approvals:
        if a["status"] == "pending":
            add("approval", a["approval_id"], a["case_id"], "An order is still waiting for a decision", a["created_at"])
    for c in cases:
        if c["status"] == "open" and c["stage"] in STUCK_STAGES:
            add(c["stage"], c["case_id"], c["case_id"], STUCK_STAGES[c["stage"]], c["updated_at"])
    for inv in invoices:
        if inv["status"] == "mismatch":
            add("invoice", inv["invoice_id"], inv["case_id"], "An invoice does not match its order", inv["created_at"])
    return sorted(found, key=lambda f: -f["hours_waiting"])
