"""What is waiting on THIS person: the home page for each department.

A person sees a queue only for the jobs they are allowed to do (the same permissions the buttons use), so
Receiving sees deliveries, Accounts sees invoices, the Approvers see orders waiting for a decision, and an
admin, who holds everything, sees all of them. Pure function: no database, clock or user lookups.

Each item is one thing to do: a title, why it is waiting, where to go, and what the button says.
"""

from datetime import date, datetime, timedelta

from app.core.config import settings
from app.core.handled import recent_handled
from app.core.invoice_chase_policy import correction_overdue

# A fresh request sits at "created" for a moment while the Purchase agent reads it; only a request stuck
# there for longer than this needs a person.
UNREAD_GRACE = timedelta(minutes=2)

_DONE = ("completed", "fulfilled_from_stock", "rejected")


def _label(case: dict | None, fallback: str = "A request") -> str:
    if not case:
        return fallback
    number, what = case.get("case_number"), case.get("items_summary") or fallback
    return f"{number} · {what}" if number else what


def _day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _item(id_: str, title: str, detail: str, link: str, action: str, urgent: bool = False, since=None, note: str | None = None,
          escalates: bool = False) -> dict:
    # `escalates` marks work the escalation rule covers: it gets a countdown (`escalates_at`) once the rule is on.
    return {"id": id_, "title": title, "detail": detail, "link": link, "action": action, "urgent": urgent, "since": since, "note": note,
            "escalates_at": None, "_escalates": escalates}


def _queue(key: str, title: str, agent: str, empty: str, items: list[dict]) -> dict:
    # urgent first, then the longest-waiting
    items = sorted(items, key=lambda i: (not i["urgent"], i["since"] or datetime.max))
    return {"key": key, "title": title, "agent": agent, "empty": empty, "items": items}


def build_my_work(username: str, can, approvals: list[dict], cases: list[dict], deliveries: list[dict],
                  invoices: list[dict], stock: list[dict], now: datetime, escalate_after_hours: float = 0,
                  chase_hours: float = 0, max_chases: int = 0, disputes: dict | None = None,
                  handled_events: list[dict] | None = None, handled_hours: float = 24,
                  po_alerts: list[dict] | None = None, goods_issues: list[dict] | None = None,
                  combine_suggestions: list[dict] | None = None, bounced_vendors: list[dict] | None = None) -> dict:
    """`can(permission)` says what this person may do. The lists are everything of that kind (the caller may
    pass an empty list for a queue the person can't see). Returns {"total", "queues": [...]}."""
    me = username.strip().lower()
    by_id = {c["case_id"].lower(): c for c in cases}
    open_cases = [c for c in cases if c["status"] == "open"]
    queues: list[dict] = []

    if can("approvals:write"):
        items = []
        for a in approvals:
            case = by_id.get(a["case_id"].lower())
            own = bool(case) and (case.get("requester_id") or "").strip().lower() == me
            rush = bool(case and case.get("urgent"))
            by = f" by {case['needed_by']:%d %b}" if rush and case.get("needed_by") else ""
            items.append(_item(
                f"approval:{a['approval_id']}", ("URGENT" + by + " · " if rush else "") + _label(case, "A vendor selection"),
                (a["reasons"] or ["Needs a decision."])[0],
                "/approvals", "Review & decide", urgent=rush, since=a["created_at"], escalates=True,
                note="You asked for this purchase, so someone else has to approve it." if own else None))
        queues.append(_queue("approval", "Orders waiting for your decision", "Approval Agent", "No orders are waiting for a decision.", items))

    if can("delivery:confirm"):
        today, items = now.date(), []
        for d in deliveries:
            case, due = by_id.get(d["case_id"].lower()), _day(d.get("expected_delivery_date"))
            late = bool(d.get("escalated_at")) or (due is not None and due < today)
            if late and due is not None:
                when = f"Overdue by {(today - due).days} day(s)" if due < today else "Overdue"
            else:
                when = f"Expected {due.day} {due:%b}" if due else "No expected date"
            chased = f" · supplier chased {d['chase_count']} time(s)" if d.get("chase_count") else ""
            if d.get("outstanding"):
                chased = f" · {d['arrived']} of {d['ordered_units']} arrived, still owed: {d['outstanding']}" + chased
            items.append(_item(f"delivery:{d['purchase_order_id']}", _label(case),
                               f"{d['po_number']} from {d['vendor_name']} · {when}{chased}", f"/cases/{d['case_id']}",
                               "Open case to mark received", urgent=late,
                               since=datetime.combine(due, datetime.min.time()) if due else None))
        for case_id, d in (disputes or {}).items():
            case = by_id.get(case_id)
            who = f"{d['by']} says" if d.get("by") else "The requester says"
            why = f": “{d['note']}”" if d.get("note") else ""
            items.append(_item(f"dispute:{case_id}", _label(case), f"{who} the goods have NOT reached them{why}", f"/cases/{case_id}",
                               "Follow up with the requester", urgent=True, since=d.get("since")))
        for g in goods_issues or []:
            case = by_id.get(g["case_id"].lower())
            what = ", ".join(f"{i['description']} × {i['quantity']}" for i in g["items"])
            state = ("A replacement is promised: record it when it arrives." if g.get("replacement_status") == "expected"
                     else "The goods were sent back. Waiting for the supplier's replacement or credit note." if g.get("return_status") == "returned" and not g.get("supplier_replied_at")
                     else "The supplier has not said how they will put it right after reminders." if g.get("escalated_at")
                     else "The supplier has replied. Read it and record how it ended." if g.get("supplier_replied_at")
                     else "Waiting for the supplier to put it right.")
            items.append(_item(f"goods-issue:{g['issue_id']}", _label(case), f"{g['po_number']} from {g['vendor_name']}: {what} ({g['kind'].replace('_', ' ')}). {state}",
                               f"/cases/{g['case_id']}", "Open case to follow up", urgent=bool(g.get("escalated_at") or g.get("supplier_replied_at")), since=g["reported_at"]))
        queues.append(_queue("delivery", "Goods expected", "Delivery Agent", "No deliveries are waiting.", items))

    if can("invoices:decide"):
        items = []
        for inv in invoices:
            if inv["status"] not in ("mismatch", "on_hold"):
                continue
            case = by_id.get(inv["case_id"].lower())
            total = inv.get("total_amount")
            amount = f" · ₹{total:,.0f}" if total is not None else ""
            number = inv.get("invoice_number") or "(number unreadable)"
            if inv["status"] == "mismatch":
                items.append(_item(f"invoice:{inv['invoice_id']}", f"{_label(case)} · Invoice {number}{amount}",
                                   inv.get("suggestion") or (inv.get("issues") or ["Does not match the order."])[0], f"/cases/{inv['case_id']}",
                                   "Review invoice", urgent=True, since=inv["created_at"], escalates=True))
            else:
                items.append(_item(f"invoice:{inv['invoice_id']}", f"{_label(case)} · Invoice {number}{amount}",
                                   inv.get("suggestion") or "Waiting for Receiving to confirm the goods arrived.", f"/cases/{inv['case_id']}",
                                   "See case", since=inv["created_at"]))
        # a rejected invoice whose supplier has had every reminder and still not sent a corrected one
        if chase_hours > 0:
            latest: dict[str, dict] = {}
            for inv in invoices:
                key = inv["case_id"].lower()
                if key not in latest or inv["created_at"] > latest[key]["created_at"]:
                    latest[key] = inv
            for inv in latest.values():
                case = by_id.get(inv["case_id"].lower())
                if inv["status"] == "rejected" and inv.get("decided_at") and case and case["status"] == "open" \
                        and correction_overdue(inv["decided_at"], now, chase_hours, max_chases):
                    items.append(_item(f"invoice-late:{inv['invoice_id']}", f"{_label(case)} · Invoice {inv.get('invoice_number') or '(number unreadable)'}",
                                       f"{inv['vendor_name']} has not sent a corrected invoice after {max_chases} reminder(s). Suggest: contact them.",
                                       f"/cases/{inv['case_id']}", "Open case", urgent=True, since=inv["decided_at"]))
        queues.append(_queue("invoice", "Invoices that need you", "Invoice Agent", "No invoices need a decision.", items))

    if can("vendors:write"):
        items = [_item(f"vendor:{c['case_id']}", _label(c), "No supplier replied before the deadline.", f"/cases/{c['case_id']}",
                       "Open case", urgent=True, since=c["updated_at"], escalates=True) for c in open_cases if c["stage"] == "sourcing_stalled"]
        for b in bounced_vendors or []:
            items.append(_item(f"vendor-email:{b['vendor_id']}", b["name"], f"Emails to {b['email']} bounce ({b.get('email_bounce_reason') or 'the address does not work'}). "
                               f"They cannot be asked for quotes until the address is fixed.", "/vendors", "Fix the address", urgent=True, since=b["email_bounced_at"]))
        for s in combine_suggestions or []:
            shared = s["matches"][0] if s.get("matches") else None
            what = (f"Both ask for {shared['item']} ({shared['secondary_qty']} and {shared['primary_qty']}). " if shared else "") + "Combine them into one order, or keep them separate?"
            items.append(_item(f"combine:{s['newer']}:{s['older']}", f"{s['newer_number']} + {s['older_number']}", what, f"/cases/{s['older']}", "Review and combine", since=s["since"]))
        queues.append(_queue("vendor", "Suppliers who haven't replied", "Vendor Agent", "Every supplier is answering.", items))

    if can("po:manage"):
        what = {"po_send_failed": "The order could not be emailed. Fix the supplier's email, then retry.",
                "po_failed": "The order could not be created automatically."}
        items = [_item(f"po:{c['case_id']}", _label(c), what[c["stage"]], f"/cases/{c['case_id']}", "Open case to retry",
                       urgent=True, since=c["updated_at"], escalates=True) for c in open_cases if c["stage"] in what]
        for a in po_alerts or []:
            case = by_id.get(a["case_id"].lower())
            kind = a["kind"]
            if kind == "problem":
                detail = f"{a['vendor_name']} replied about {a['po_number']} and raised a problem: {a['vendor_issue']}"
            elif kind == "cancel_refused":
                detail = f"{a['vendor_name']} says {a['po_number']} cannot be cancelled. Settle it with them, or carry on with the order."
            elif kind == "cancel_overdue":
                detail = f"{a['vendor_name']} has not answered the request to cancel {a['po_number']} after {a['cancel_chase_count']} reminder(s)."
            elif kind == "change":
                what = "; ".join(f"{c['item']}: {c['from']} → {c['to']}" for c in a["changes"])
                detail = f"{a['by'] or 'The requester'} asks to change {a['po_number']} with {a['vendor_name']}: {what}. Agree it with the supplier, then record the result."
            else:
                detail = f"{a['vendor_name']} has not confirmed {a['po_number']} after {a['confirm_chase_count']} reminder(s)."
            since = a.get("cancel_escalated_at") or a.get("cancel_refused_at") or a.get("confirm_escalated_at") or a.get("sent_at")
            items.append(_item(f"po-{kind}:{a['case_id'].lower()}", _label(case), detail, f"/cases/{a['case_id']}",
                               "Open case to follow up", urgent=True, since=since))
        queues.append(_queue("po", "Purchase orders that need a hand", "PO Agent", "Every order went out.", items))

    if can("cases:write"):
        items = [_item(f"purchase:{c['case_id']}", _label(c, "A request"), "The request could not be read automatically.",
                       f"/cases/{c['case_id']}", "Open case", urgent=True, since=c["updated_at"])
                 for c in open_cases if c["stage"] == "created" and now - c["updated_at"] > UNREAD_GRACE]
        queues.append(_queue("purchase", "Requests that couldn't be read", "Purchase Agent", "Every request was understood.", items))

    if can("stock:write"):
        items = []
        for row in stock:
            left = row["quantity_available"]
            if left <= settings.LOW_STOCK_AT:
                items.append(_item(f"stock:{row['item_description']}", row["item_description"],
                                   "Out of stock" if left <= 0 else f"Only {left} left", "/stock", "Open stock", urgent=left <= 0))
        queues.append(_queue("stores", "Stock running low", "Procurement Agent", "Stock levels are fine.", items))

    if escalate_after_hours > 0:  # past the escalation time: urgent, and say the admin has been told
        late = timedelta(hours=escalate_after_hours)
        for q in queues:
            for item in q["items"]:
                if item["_escalates"] and item["since"]:
                    item["escalates_at"] = item["since"] + late
                if item["since"] and now - item["since"] > late and q["key"] != "delivery":
                    item["urgent"] = True
                    item["note"] = item["note"] or f"Waiting more than {escalate_after_hours:g} hours, so the admin has been told."
            q["items"].sort(key=lambda i: (not i["urgent"], i["since"] or datetime.max))

    for q in queues:
        for item in q["items"]:
            item.pop("_escalates", None)  # internal marker, not part of the answer

    done = recent_handled(handled_events or [], by_id, now, handled_hours, {q["key"] for q in queues})
    for q in queues:
        q["handled"] = done.get(q["key"], [])
    return {"total": sum(len(q["items"]) for q in queues), "queues": queues}
