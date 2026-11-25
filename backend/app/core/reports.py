"""The management report: spend, how long each stage takes, how much ran with no person, and how each supplier performs.

Pure functions over rows the controller gathers (cases, events, quote requests, orders, invoices); no database or clock.
Everything is worked out from what already happened, so nothing extra is stored.
"""

from collections import defaultdict
from datetime import date, datetime

from app.core.agent_steps import STEPS

# An event that means a person was needed -> (the agent that got stuck, what went wrong). Goods arriving, an approver
# signing off a big order and so on are also people, but the approval request is the signal that a person was needed.
EXCEPTIONS: dict[str, tuple[str, str]] = {
    "sourcing.stalled": ("Vendor", "No supplier replied in time"),
    "sourcing.no_vendors": ("Vendor", "No supplier could be emailed"),
    "approval.requested": ("Approval", "The order needed a person's approval"),
    "po.send_failed": ("PO", "The order could not be emailed"),
    "po.confirmation_overdue": ("PO", "The supplier never confirmed the order"),
    "po.vendor_problem": ("PO", "The supplier raised a problem with the order"),
    "delivery.escalated": ("Delivery", "The delivery was overdue"),
    "delivery.requester_disputed": ("Delivery", "The requester said the goods had not arrived"),
    "invoice.mismatch": ("Invoice", "The invoice did not match the order"),
    "invoice.correction_overdue": ("Invoice", "The supplier never sent a corrected invoice"),
    "worker.error": ("Operations", "An automatic step failed"),
}

REPORT_EVENT_TYPES = tuple(EXCEPTIONS) + (
    "step.failed", "rfq.sent", "vendor.selected", "po.issued", "po.confirmed", "delivery.received", "invoice.matched",
    "invoice.approved", "case.closed",
)

STAGE_LABEL = {
    "created": "Reading the request", "purchase_request_created": "Checking stock", "sourcing_needed": "Asking suppliers",
    "awaiting_quotes": "Waiting for supplier quotes", "sourcing_stalled": "No supplier replied",
    "vendor_selected": "Choosing a supplier", "awaiting_approval": "Waiting for an approval", "approved": "Placing the order",
    "po_send_failed": "Order could not be emailed", "po_failed": "Order could not be created",
    "po_issued": "Order placed, waiting for delivery", "delivery_late": "Delivery overdue", "delivered": "Waiting for the invoice",
}


def _hours(a: datetime | None, b: datetime | None) -> float | None:
    return (b - a).total_seconds() / 3600 if a and b else None


def _avg(values: list[float | None], places: int = 1) -> float | None:
    real = [v for v in values if v is not None]
    return round(sum(real) / len(real), places) if real else None


def _day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _first_last(events: list[dict]) -> dict[str, dict[str, datetime]]:
    """For each case: the first and the last time each kind of event happened."""
    seen: dict[str, dict[str, dict[str, datetime]]] = defaultdict(lambda: defaultdict(dict))
    for e in sorted(events, key=lambda e: e["created_at"]):
        slot = seen[e["case_id"].lower()][e["event_type"]]
        slot.setdefault("first", e["created_at"])
        slot["last"] = e["created_at"]
    return seen


def _exceptions(events: list[dict]) -> dict[str, set[tuple[str, str]]]:
    """Per case, what needed a person (each agent and reason once per case)."""
    out: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for e in events:
        case_id = e["case_id"].lower()
        if e["event_type"] in EXCEPTIONS:
            out[case_id].add(EXCEPTIONS[e["event_type"]])
        elif e["event_type"] == "step.failed":
            step = STEPS.get((e.get("payload") or {}).get("step"))
            out[case_id].add((step.agent.replace(" Agent", "") if step else "Operations", "A step failed"))
    return out


def _automation(cases: list[dict], exceptions: dict[str, set[tuple[str, str]]]) -> dict:
    cases = [c for c in cases if c["stage"] not in ("cancelled", "merged")]       # withdrawn requests say nothing about automation
    needed = [c for c in cases if exceptions.get(c["case_id"].lower())]
    clean = [c for c in cases if not exceptions.get(c["case_id"].lower())]
    touchless = [c for c in clean if c["status"] == "closed"]
    by_agent: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for case_id, items in exceptions.items():
        for agent, label in items:
            by_agent[agent][label].add(case_id)
    agents = []
    for agent, reasons in by_agent.items():
        every = set().union(*reasons.values())
        agents.append({"agent": agent, "cases": len(every),
                       "reasons": sorted(({"label": label, "cases": len(ids)} for label, ids in reasons.items()), key=lambda r: -r["cases"])})
    decided = len(touchless) + len(needed)
    return {
        "touchless": len(touchless), "needed_a_person": len(needed), "in_progress_so_far_clean": len(clean) - len(touchless),
        "touchless_pct": round(100 * len(touchless) / decided) if decided else None,
        "by_agent": sorted(agents, key=lambda a: -a["cases"]),
    }


def _stage_times(cases: list[dict], marks: dict) -> list[dict]:
    """Average time between the steps of a request, over the requests that went through both ends."""
    def step(label, start, end):
        gaps = []
        for c in cases:
            m = marks.get(c["case_id"].lower(), {})
            a, b = start(c, m), end(c, m)
            gap = _hours(a, b)
            if gap is not None and gap >= 0:
                gaps.append(gap)
        return {"label": label, "avg_hours": _avg(gaps), "count": len(gaps)}

    first = lambda m, kind: (m.get(kind) or {}).get("first")
    last = lambda m, kind: (m.get(kind) or {}).get("last")
    cleared = lambda c, m: min((t for t in (first(m, "invoice.matched"), first(m, "invoice.approved")) if t), default=None)
    return [
        step("Asking suppliers until a supplier is chosen", lambda c, m: first(m, "rfq.sent"), lambda c, m: first(m, "vendor.selected")),
        step("Supplier chosen until the order is placed (includes any approval)", lambda c, m: last(m, "vendor.selected"), lambda c, m: first(m, "po.issued")),
        step("Order placed until the supplier confirms", lambda c, m: first(m, "po.issued"), lambda c, m: first(m, "po.confirmed")),
        step("Order placed until the goods are received", lambda c, m: first(m, "po.issued"), lambda c, m: first(m, "delivery.received")),
        step("Goods received until the invoice is cleared", lambda c, m: first(m, "delivery.received"), cleared),
        step("Whole request, start to finish", lambda c, m: c["created_at"], lambda c, m: last(m, "case.closed") if c["stage"] == "completed" else None),
    ]


def _stuck(cases: list[dict], now: datetime) -> list[dict]:
    by_stage: dict[str, list[float]] = defaultdict(list)
    for c in cases:
        if c["status"] == "open":
            by_stage[c["stage"]].append(_hours(c["updated_at"], now) or 0)
    return sorted(({"stage": s, "label": STAGE_LABEL.get(s, s.replace("_", " ").capitalize()), "count": len(h),
                    "oldest_hours": round(max(h), 1), "avg_hours": round(sum(h) / len(h), 1)} for s, h in by_stage.items()),
                  key=lambda r: -r["oldest_hours"])


def _spend(pos: list[dict]) -> dict:
    by_vendor: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "orders": 0})
    by_month: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "orders": 0})
    for p in pos:
        amount = float(p["total_amount"] or 0)
        v, m = by_vendor[p["vendor_name"]], by_month[f"{p['created_at']:%Y-%m}"]
        v["total"] += amount
        v["orders"] += 1
        m["total"] += amount
        m["orders"] += 1
    return {
        "total": round(sum(float(p["total_amount"] or 0) for p in pos), 2), "orders": len(pos),
        "by_vendor": sorted(({"vendor": k, **{"total": round(v["total"], 2), "orders": v["orders"]}} for k, v in by_vendor.items()), key=lambda r: -r["total"]),
        "by_month": [{"month": k, "total": round(v["total"], 2), "orders": v["orders"]} for k, v in sorted(by_month.items())],
    }


def _suppliers(rfqs: list[dict], pos: list[dict], invoices: list[dict], events: list[dict], now: datetime) -> list[dict]:
    names: dict[str, str] = {}
    for row in rfqs + pos:
        names[row["vendor_id"].lower()] = row["vendor_name"]
    po_sent = {p["case_id"].lower(): p.get("sent_at") for p in pos}
    email_confirms: dict[str, list[float]] = defaultdict(list)
    vendor_of_case = {p["case_id"].lower(): p["vendor_id"].lower() for p in pos}
    for e in events:
        if e["event_type"] == "po.confirmed" and (e.get("payload") or {}).get("via") == "email":
            case_id = e["case_id"].lower()
            gap = _hours(po_sent.get(case_id), e["created_at"])
            if gap is not None and case_id in vendor_of_case:
                email_confirms[vendor_of_case[case_id]].append(gap)

    out = []
    for vid, name in names.items():
        mine_rfq = [r for r in rfqs if r["vendor_id"].lower() == vid]
        mine_po = [p for p in pos if p["vendor_id"].lower() == vid]
        mine_inv = [i for i in invoices if i["vendor_id"].lower() == vid]
        replied = [r for r in mine_rfq if r.get("replied_at")]
        sent = [p for p in mine_po if p["status"] == "sent"]
        confirmed = [p for p in sent if p.get("acknowledged_at")]
        today = now.date()
        late_days = []
        delivered = 0
        for p in mine_po:
            due = _day(p.get("expected_delivery_date"))
            if due is None:
                continue
            if p["delivery_status"] == "delivered":
                delivered += 1
                got = _day(p.get("delivered_at"))
                if got and got > due:
                    late_days.append((got - due).days)
            elif p["status"] == "sent" and today > due:
                late_days.append((today - due).days)
        out.append({
            "vendor_id": vid, "name": name,
            "asked": len(mine_rfq), "replied": len(replied),
            "reply_rate": round(100 * len(replied) / len(mine_rfq)) if mine_rfq else None,
            "avg_reply_hours": _avg([_hours(r["sent_at"], r["replied_at"]) for r in replied]),
            "orders": len(mine_po), "spend": round(sum(float(p["total_amount"] or 0) for p in mine_po), 2),
            "confirm_rate": round(100 * len(confirmed) / len(sent)) if sent else None,
            "avg_confirm_hours": _avg(email_confirms.get(vid, [])),
            "delivered": delivered, "late": len(late_days), "avg_days_late": _avg([float(d) for d in late_days]),
            "invoices": len(mine_inv), "invoice_problems": sum(1 for i in mine_inv if i["status"] in ("mismatch", "rejected")),
        })
    return sorted(out, key=lambda s: (-s["spend"], -s["asked"], s["name"]))


def build_report(cases: list[dict], events: list[dict], rfqs: list[dict], pos: list[dict], invoices: list[dict],
                 now: datetime, days: int) -> dict:
    """`cases` are the requests started in the period; the other rows belong to those requests."""
    marks = _first_last(events)
    exceptions = _exceptions(events)
    completed = [c for c in cases if c["stage"] == "completed"]
    cycle = [_hours(c["created_at"], (marks.get(c["case_id"].lower(), {}).get("case.closed") or {}).get("last")) for c in completed]
    spend = _spend(pos)
    return {
        "days": days,
        "generated_at": now,
        "totals": {
            "requests": len(cases), "completed": len(completed),
            "from_stock": sum(1 for c in cases if c["stage"] == "fulfilled_from_stock"),
            "rejected": sum(1 for c in cases if c["stage"] == "rejected"),
            "cancelled": sum(1 for c in cases if c["stage"] in ("cancelled", "merged")),
            "in_progress": sum(1 for c in cases if c["status"] == "open"),
            "spend": spend["total"], "orders": spend["orders"], "avg_cycle_hours": _avg(cycle),
        },
        "automation": _automation(cases, exceptions),
        "spend": spend,
        "stage_times": _stage_times(cases, marks),
        "stuck": _stuck(cases, now),
        "suppliers": _suppliers(rfqs, pos, invoices, events, now),
    }
