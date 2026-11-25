"""What the bell shows. Built from live state (no separate table), so it can never go stale:
staff see what currently needs a person; a requester sees milestones on their OWN requests.
Pure functions, no DB access, so the wording and rules are easy to test."""

from datetime import datetime, timedelta

# Staff: open cases stuck in these stages need a person.
_STAFF_STAGES = {
    "sourcing_stalled": ("Suppliers not responding", "No supplier quotes came in. Follow up with suppliers."),
    "po_send_failed": ("Purchase order not sent", "The purchase order could not be emailed. Fix the supplier's email and retry."),
    "po_failed": ("Purchase order failed", "The purchase order could not be created automatically."),
    "delivery_late": ("Delivery overdue", "The supplier has not delivered after repeated follow-ups. Contact them."),
}

# Requester: friendly milestones on their own requests (internal detail is never shown).
_REQUESTER_STAGES = {
    "fulfilled_from_stock": ("Available in stock", "It's in stock and will be dispatched to you."),
    "awaiting_approval": ("Waiting for approval", "A manager is reviewing your request."),
    "po_issued": ("Order placed", "Your order has been placed with the supplier."),
    "delivery_late": ("Delivery delayed", "Delivery is running late. Our team is following up."),
    "sourcing_stalled": ("Taking longer than usual", "Our team has been told and will follow up."),
    "delivered": ("Delivered", "Your request has been delivered."),
    "completed": ("Request complete", "Your request is complete."),
    "rejected": ("Not approved", "Your request wasn't approved. Please speak to your manager."),
}

REQUESTER_WINDOW = timedelta(days=14)
MAX_ITEMS = 30


def _summary(case: dict) -> str:
    return case.get("items_summary") or "A request"


# The permission that marks the department a stuck case belongs to.
_STAGE_PERMISSION = {
    "sourcing_stalled": "vendors:write", "po_send_failed": "po:manage", "po_failed": "po:manage", "delivery_late": "delivery:confirm",
}


def staff_items(pending_approvals: list[dict], cases: list[dict], bad_invoices: list[dict], can=lambda permission: True) -> list[dict]:
    """What needs a person. `can(permission)` limits it to the person's own departments (the default shows all)."""
    pending_approvals = pending_approvals if can("approvals:write") else []
    bad_invoices = bad_invoices if can("invoices:decide") else []
    open_cases = {c["case_id"]: c for c in cases if c["status"] == "open"}
    items = []

    for a in pending_approvals:
        case = open_cases.get(a["case_id"])
        reason = a["reasons"][0] if a["reasons"] else "Needs a decision."
        items.append({
            "id": f"approval:{a['approval_id']}", "kind": "approval", "requires_action": True,
            "title": "Approval needed", "link": "/approvals", "created_at": a["created_at"],
            "message": f"{_summary(case) if case else 'A vendor selection'}: {reason}",
        })

    for c in open_cases.values():
        if c["stage"] in _STAFF_STAGES and can(_STAGE_PERMISSION[c["stage"]]):
            title, message = _STAFF_STAGES[c["stage"]]
            items.append({
                "id": f"case:{c['case_id']}:{c['stage']}", "kind": "case", "requires_action": True,
                "title": title, "link": f"/cases/{c['case_id']}", "created_at": c["updated_at"],
                "message": f"{_summary(c)}: {message}",
            })

    for inv in bad_invoices:
        items.append({
            "id": f"invoice:{inv['invoice_id']}", "kind": "invoice", "requires_action": True,
            "title": "Invoice needs review", "link": f"/cases/{inv['case_id']}", "created_at": inv["created_at"],
            "message": f"Invoice {inv['invoice_number'] or '(unreadable number)'} from {inv['vendor_name']} "
                       f"does not match {inv['po_number']}.",
        })

    return _newest_first(items)


def requester_items(own_cases: list[dict], now: datetime) -> list[dict]:
    items = []
    for c in own_cases:
        stage = "completed" if c["status"] == "closed" and c["stage"] == "completed" else c["stage"]
        if stage not in _REQUESTER_STAGES or now - c["updated_at"] > REQUESTER_WINDOW:
            continue
        title, message = _REQUESTER_STAGES[stage]
        items.append({
            "id": f"mine:{c['case_id']}:{stage}", "kind": "my_request", "requires_action": False,
            "title": title, "link": f"/requests/{c['case_id']}", "created_at": c["updated_at"],
            "message": f"{_summary(c)}: {message}",
        })
    return _newest_first(items)


def _newest_first(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda i: i["created_at"], reverse=True)[:MAX_ITEMS]
