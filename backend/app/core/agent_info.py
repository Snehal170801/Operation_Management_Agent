"""Everything one agent did on one case, laid out for a person to read (what you see when you click an agent).

Pure functions: the controller gathers the stored facts (the request, the supplier replies, the ranking, the
approval, the order, the delivery, the invoice and its match...) and this module turns them into sections.

Two audiences, decided here and nowhere else:
  staff      the full picture: names, prices, the rules that were checked and how each came out
  requester  the same story without money, supplier names or internal reasons

A section is one of: facts (label/value pairs), text, table, checks (rule + pass/fail/info/wait), timeline.
"""

from datetime import datetime

from app.core.agent_flow import _feed_line, _short
from app.core import tax
from app.core.config import settings

AGENT_KEYS = ("purchase", "procurement", "vendor", "approval", "po", "delivery", "invoice", "operations", "notification")

NAMES = {
    "purchase": "Purchase Agent", "procurement": "Procurement Agent", "vendor": "Vendor Agent", "approval": "Approval Agent",
    "po": "PO Agent", "delivery": "Delivery Agent", "invoice": "Invoice Agent", "operations": "Operations Agent",
    "notification": "Notification Agent",
}
ROLES = {
    "purchase": "Reads the request and breaks it into items", "procurement": "Checks the Store Room",
    "vendor": "Asks suppliers for prices, reads their replies and picks one", "approval": "Decides whether a person must sign off",
    "po": "Creates the purchase order and sends it", "delivery": "Follows up until the goods arrive",
    "invoice": "Reads the supplier's invoice and matches it against the order",
    "operations": "Keeps the record of everything that happens", "notification": "Tells a person when they are needed",
}
TIMELINE_LIMIT = 40


# ------------------------------------------------------------------------------------ small building blocks

def money(value) -> str:
    return "—" if value is None else f"₹{value:,.0f}" if float(value).is_integer() else f"₹{value:,.2f}"


def _when(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)


def facts(title: str, pairs: list[tuple[str, object]]) -> dict | None:
    items = [{"label": label, "value": str(value)} for label, value in pairs if value not in (None, "")]
    return {"title": title, "kind": "facts", "items": items} if items else None


def text(title: str, body: str | None) -> dict | None:
    return {"title": title, "kind": "text", "body": body} if body else None


def table(title: str, columns: list[str], rows: list[list], highlight: int | None = None) -> dict | None:
    if not rows:
        return None
    return {"title": title, "kind": "table", "columns": columns, "rows": [[("—" if c is None else str(c)) for c in r] for r in rows],
            "highlight": highlight}


def check(label: str, status: str, detail: str = "") -> dict:
    return {"label": label, "status": status, "detail": detail}  # status: pass | fail | info | wait


def checks(title: str, items: list[dict]) -> dict | None:
    return {"title": title, "kind": "checks", "items": items} if items else None


def _timeline(events: list[dict], agent_names: set[str], staff: bool) -> dict | None:
    """What this agent did, newest first, in the same safe wording the live feed uses."""
    lines = []
    for e in events:
        line = _feed_line(e, staff)
        if line and line[0] in agent_names:
            lines.append({"at": _when(e["created_at"]), "text": line[1], "tone": line[2], "id": e["event_id"]})
    lines.sort(key=lambda i: i["id"], reverse=True)
    items = [{k: v for k, v in i.items() if k != "id"} for i in lines[:TIMELINE_LIMIT]]
    return {"title": "What it did", "kind": "timeline", "items": items} if items else None


def _event(events: list[dict], event_type: str) -> dict | None:
    return next((e for e in reversed(events) if e["event_type"] == event_type), None)


# ------------------------------------------------------------------------------------------ each agent

def _purchase(d: dict, staff: bool) -> list:
    r = d.get("request")
    if not r:
        return []
    return [
        text("What they wrote", r["raw_request"]),
        table("What the Purchase agent understood", ["Item", "Quantity"], [[i["description"], i["quantity"]] for i in r["items"]]),
        facts("Request", [("Cost centre", r.get("cost_center")), ("Sent", _when(r.get("created_at"))),
                          ("Requested by", d["case"].get("requester_id") if staff else None)]),
    ]


def _procurement(d: dict, staff: bool) -> list:
    e = _event(d["events"], "stock.checked")
    if not e:
        return []
    p = e["payload"]
    verdict = "Everything was in stock, so the request was filled from the Store Room." if p.get("sufficient") \
        else "Not enough in stock, so the request went out to suppliers."
    if not staff:
        return [facts("Stock check", [("Result", verdict)])]
    rows = [[c["description"], c["requested"], c["available"], c.get("stock_item") or "no match in the Store Room",
             "Yes" if c["sufficient"] else "No"] for c in p.get("checks", [])]
    return [facts("Stock check", [("Result", verdict)]),
            table("Item by item", ["Asked for", "Quantity", "In stock", "Matched to", "Enough?"], rows)]


def _vendor(d: dict, staff: bool) -> list:
    rfqs, quotes, sel = d.get("rfqs", []), d.get("quotes", []), d.get("selection")
    if not rfqs and not quotes:
        return []
    replied = sum(1 for r in rfqs if r["status"] == "replied")
    reminders = sum(r.get("reminder_count") or 0 for r in rfqs)
    deadline = max((r["deadline_at"] for r in rfqs if r.get("deadline_at")), default=None)
    summary = facts("Suppliers", [("Asked", len(rfqs)), ("Replied", f"{replied} of {len(rfqs)}"),
                                  ("Reminders sent", reminders or "none"), ("Reply deadline", _when(deadline) if staff else None)])
    if not staff:
        return [summary]

    vendors = d.get("vendors", {})
    asked = table("Who was asked", ["Supplier", "Email", "Asked", "Status", "Replied", "Reminders"], [
        [r["vendor_name"], (vendors.get(r["vendor_id"]) or {}).get("email"), _when(r.get("sent_at")),
         "Replied" if r["status"] == "replied" else r["status"].replace("_", " ").title(), _when(r.get("replied_at")),
         r.get("reminder_count") or 0] for r in rfqs])
    chosen = next((i for i, q in enumerate(quotes) if sel and q["vendor_id"] == sel["vendor_id"]), None)
    replies = table("What each supplier replied", ["Supplier", "Price", "Delivery", "Terms", "Reliability", "What they wrote"], [
        [q["vendor_name"], money(q["price"]), f"{q['lead_time_days']} days" if q["lead_time_days"] is not None else None, q["terms"],
         (vendors.get(q["vendor_id"]) or {}).get("reliability_score"), (q["raw_quote_text"] or "")[:160]] for q in quotes], chosen)
    ranked = None
    ranking = next((e["payload"]["ranking"] for e in reversed(d["events"])
                    if e["event_type"] == "vendor.selected" and (e.get("payload") or {}).get("ranking")), [])
    if ranking:
        by_vendor = {q["vendor_id"]: q for q in quotes}
        ranked = table("The AI's ranking, best first", ["#", "Supplier", "Price", "Delivery", "Why"], [
            [r["rank"], (by_vendor.get(r["vendor_id"]) or {}).get("vendor_name"), money((by_vendor.get(r["vendor_id"]) or {}).get("price")),
             f"{by_vendor[r['vendor_id']]['lead_time_days']} days" if by_vendor.get(r["vendor_id"], {}).get("lead_time_days") is not None else None,
             r.get("reason")] for r in ranking])
    earlier_quotes = d.get("earlier_quotes") or []
    earlier = table("Earlier offers (turned down, so suppliers were asked again)", ["Supplier", "Price", "Delivery", "Replied"], [
        [q["vendor_name"], money(q["price"]), f"{q['lead_time_days']} days" if q["lead_time_days"] is not None else None, _when(q.get("created_at"))]
        for q in earlier_quotes]) if earlier_quotes else None
    why = text(f"Why {sel['vendor_name']} is selected", sel["rationale"]) if sel else None
    cheapest = min((q for q in quotes if q["price"] is not None), key=lambda q: q["price"], default=None)
    note = None
    if sel and cheapest and cheapest["vendor_id"] != sel["vendor_id"]:
        note = text("Note", f"{cheapest['vendor_name']} was cheaper ({money(cheapest['price'])}); the choice also weighs delivery time, terms and reliability.")
    return [summary, asked, replies, ranked, why, note, earlier]


def _approval(d: dict, staff: bool) -> list:
    approvals = d.get("approvals", [])
    a = approvals[-1] if approvals else None
    if a is None:
        return []
    status = a["status"]
    decision = {"auto_approved": "Approved automatically", "approved": "Approved by a person", "rejected": "Not approved",
                "pending": "Waiting for a person to decide", "superseded": "Replaced by a newer decision"}.get(status, status)
    if not staff:
        return [facts("Decision", [("Result", decision)])]

    quotes, sel, vendors = d.get("quotes", []), d.get("selection"), d.get("vendors", {})
    quote = next((q for q in quotes if sel and q["vendor_id"] == sel["vendor_id"]), None)
    price = tax.cost(quote["price"], settings.TAX_RATE_PCT, settings.TAX_INCLUDED_IN_QUOTES) if quote else None       # (with tax when a rate is set: what the limit is about)
    reliability = (vendors.get(sel["vendor_id"]) or {}).get("reliability_score") if sel else None
    rules = [
        check("Order value is within the automatic limit",
              "info" if price is None else "pass" if price <= settings.AUTO_APPROVE_MAX_AMOUNT else "fail",
              f"{money(price)} against a limit of {money(settings.AUTO_APPROVE_MAX_AMOUNT)}"),
        check("Supplier is reliable enough",
              "info" if reliability is None else "pass" if reliability >= settings.AUTO_APPROVE_MIN_RELIABILITY else "fail",
              f"Rated {reliability} · needs {settings.AUTO_APPROVE_MIN_RELIABILITY} or more"),
        check("Enough quotes to compare", "pass" if len(quotes) >= settings.AUTO_APPROVE_MIN_QUOTES else "fail",
              f"{len(quotes)} received · needs {settings.AUTO_APPROVE_MIN_QUOTES} or more"),
    ]
    return [
        facts("Decision", [("Result", decision), ("Decided by", a.get("decided_by")), ("When", _when(a.get("decided_at"))),
                           ("Note", a.get("decision_note"))]),
        checks("Rules checked", rules),
        text("Why a person was needed", "; ".join(a["reasons"])) if a.get("reasons") else None,
    ]


def _po(d: dict, staff: bool) -> list:
    po = d.get("po")
    if not po:
        return []
    items = table("What was ordered", ["Item", "Quantity"], [[i["description"], i["quantity"]] for i in po["items"]])
    confirmed = "Confirmed" if po.get("acknowledged_at") else "Not yet confirmed"
    if not staff:
        return [facts("Order", [("Status", "Sent to the supplier" if po["status"] == "sent" else po["status"].replace("_", " ").title()),
                                ("Supplier confirmation", confirmed if po["status"] == "sent" else None),
                                ("Sent", _when(po.get("sent_at"))), ("Expected by", _when(po.get("expected_delivery_date")))]), items]
    return [facts("Order", [("Number", po["po_number"]), ("Supplier", po["vendor_name"]), ("Total", money(po["total_amount"])),
                            ("Terms", po.get("terms")), ("Promised delivery", f"{po['lead_time_days']} days" if po.get("lead_time_days") is not None else None),
                            ("Expected by", _when(po.get("expected_delivery_date"))), ("Status", po["status"].title()),
                            ("Created", _when(po.get("created_at"))), ("Emailed", _when(po.get("sent_at")))]), items,
            facts("Did the supplier confirm?", [
                ("Result", f"Confirmed on {_when(po['acknowledged_at'])}" if po.get("acknowledged_at") else
                 "The supplier has not confirmed after reminders" if po.get("confirm_escalated_at") else
                 "Waiting for the supplier" if po["status"] == "sent" else None),
                ("Confirmed by", po.get("acknowledged_by")),
                ("Reminders sent", po.get("confirm_chase_count") if po["status"] == "sent" and not po.get("acknowledged_at") else None),
                ("Problem they raised", po.get("vendor_issue"))])]


def _delivery(d: dict, staff: bool) -> list:
    dl = d.get("delivery")
    if not dl:
        return []
    got = dl["delivery_status"] == "delivered"
    status = "Received" if got else "On its way" if not dl.get("escalated_at") else "Overdue"
    if not staff:
        return [facts("Delivery", [("Status", status), ("Expected by", _when(dl.get("expected_delivery_date"))),
                                   ("Received", _when(dl.get("delivered_at")))])]
    parts = table("Delivered so far", ["Item", "Ordered", "Received", "Still owed"],
                  [[l["description"], l["ordered"], l["received"], l["outstanding"]] for l in dl.get("items", [])]) if dl.get("batches") else None
    return [facts("Delivery", [("Status", "Part delivered" if dl.get("partial") else status), ("Expected by", _when(dl.get("expected_delivery_date"))),
                               ("Accepted short", _when(dl.get("short_closed_at"))),
                               ("Supplier chased", f"{dl['chase_count']} time(s) automatically" if not got else None),
                               ("Last chased", _when(dl.get("last_chased_at"))), ("Marked overdue", _when(dl.get("escalated_at"))),
                               ("Received", _when(dl.get("delivered_at"))), ("Received by", dl.get("received_by")),
                               ("Note", dl.get("delivery_note")), ("Order", dl["po_number"])]), parts]


def _invoice_checks(inv: dict, po: dict | None, goods_received: bool) -> list[dict]:
    """How the invoice was matched against the order and the receipt, rule by rule. Re-derived from what was
    stored; the stored result (matched / on hold / mismatch) is the authority, this shows why."""
    issues = " ".join(inv.get("issues") or []).lower()
    ex = inv.get("extracted") or {}
    rules = [
        check("Invoice number could be read", "pass" if inv.get("invoice_number") else "fail", inv.get("invoice_number") or "not found"),
        check("Not a duplicate", "fail" if "duplicate" in issues else "pass", "Each supplier invoice number can be used once"),
    ]
    if po:
        rules.append(check("From the supplier on the order", "pass" if inv["vendor_id"] == po["vendor_id"] else "fail", po["vendor_name"]))
        quoted = ex.get("po_number")
        rules.append(check("Quotes the right order number",
                           "info" if not quoted else "pass" if quoted.strip().upper() == po["po_number"].upper() else "fail",
                           f"{quoted} against {po['po_number']}" if quoted else f"Order number not stated · order is {po['po_number']}"))
        total, agreed = inv.get("total_amount"), po.get("total_amount")
        if total is None or agreed is None:
            rules.append(check("Total matches the order", "fail", "The total could not be read" if total is None else "The order has no agreed total"))
        else:
            allowed = abs(agreed) * settings.INVOICE_AMOUNT_TOLERANCE_PCT / 100
            ok = abs(total - agreed) <= allowed
            rules.append(check("Total matches the order", "pass" if ok else "fail",
                               f"Invoice {money(total)} · order {money(agreed)} · allowed difference {settings.INVOICE_AMOUNT_TOLERANCE_PCT:g}%"))
        billed, ordered = sum(i["quantity"] for i in ex.get("items") or []), sum(i["quantity"] for i in po["items"])
        rules.append(check("Quantity matches the order", "info" if not ex.get("items") else "pass" if billed == ordered else "fail",
                           f"Invoice {billed} · ordered {ordered}" if ex.get("items") else f"Quantities not itemised · ordered {ordered}"))
    rules.append(check("Goods confirmed as received", "pass" if goods_received else "wait",
                       "A person confirmed the goods arrived" if goods_received else "Waiting for someone to confirm the goods arrived"))
    return rules


def _invoice(d: dict, staff: bool) -> list:
    invoices = d.get("invoices", [])
    if not invoices:
        return []
    verdict = {"matched": "Matched, cleared for payment", "on_hold": "On hold, waiting for the goods", "mismatch": "Needs a closer look",
               "approved": "Approved by a person", "rejected": "Rejected"}
    out: list = []
    for inv in invoices:
        if not staff:
            out.append(facts("Invoice", [("Status", {"matched": "Checked and cleared", "approved": "Checked and cleared",
                                                      "rejected": "Not accepted"}.get(inv["status"], "Being checked"))]))
            continue
        label = f"Invoice {inv['invoice_number'] or '(no number)'}"
        out += [
            text(f"Our suggestion for {inv['invoice_number'] or 'this invoice'}", inv.get("suggestion")),
            facts(label, [("Supplier", inv["vendor_name"]), ("Total", money(inv.get("total_amount"))), ("Order", inv["po_number"]),
                          ("Arrived by", inv["source"]), ("Received", _when(inv.get("created_at"))),
                          ("Result", verdict.get(inv["status"], inv["status"])), ("Decided by", inv.get("decided_by")),
                          ("Decision note", inv.get("decision_note"))]),
            checks("How it was matched", _invoice_checks(inv, d.get("po"), (d.get("delivery") or {}).get("delivery_status") == "delivered")),
            text("Problems found", " ".join(inv["issues"])) if inv["status"] == "mismatch" and inv.get("issues") else None,
            text("What the supplier sent", (inv.get("raw_text") or "").strip()[:700]),
        ]
    return out


def _operations(d: dict, staff: bool) -> list:
    events, case = d["events"], d["case"]
    closed = _event(events, "case.closed")
    stages = [e for e in events if e["event_type"].startswith("stage.")]
    return [
        facts("The record", [("Steps recorded", len(events)), ("Opened", _when(case.get("created_at"))),
                             ("Current stage", case["stage"].replace("_", " ").title()),
                             ("Closed", _when(closed["created_at"]) if closed else None),
                             ("Requested by", case.get("requester_id") if staff else None)]),
        {"title": "Every move the case made", "kind": "timeline", "items": [
            {"at": _when(e["created_at"]), "text": e["event_type"][len("stage."):].replace("_", " ").capitalize(), "tone": "info"}
            for e in reversed(stages)][:TIMELINE_LIMIT]} if stages else None,
    ]


def _notification(d: dict, staff: bool) -> list:
    notes = [e for e in d["events"] if e["event_type"] in ("notification.sent", "notification.no_recipients")]
    if not notes:
        return [facts("Emails to people", [("Result", "Nothing has needed a person yet, so nobody has been emailed.")])]
    items = []
    for e in reversed(notes):
        p = e.get("payload") or {}
        if e["event_type"] == "notification.no_recipients":
            line, tone = ("Nobody could be reached" if staff else "Could not reach anyone yet"), "warn"
        elif staff:
            line, tone = f"Emailed {p.get('sent', 0)} approver(s) about {str(p.get('kind', 'an update')).replace('_', ' ')}" + \
                         (f" ({p['failed']} failed)" if p.get("failed") else ""), "ok" if not p.get("failed") else "warn"
        else:
            line, tone = "A person was told", "ok"
        items.append({"at": _when(e["created_at"]), "text": line, "tone": tone})
    return [facts("Emails to people", [("Times someone was told", len(notes))]), {"title": "What it did", "kind": "timeline", "items": items}]


_BUILDERS = {
    "purchase": _purchase, "procurement": _procurement, "vendor": _vendor, "approval": _approval, "po": _po,
    "delivery": _delivery, "invoice": _invoice, "operations": _operations, "notification": _notification,
}
_OWN_TIMELINE = {"purchase", "procurement", "vendor", "approval", "po", "delivery", "invoice"}


def build_agent_info(key: str, d: dict, staff: bool) -> dict:
    """`d` holds what the controller gathered: case, events, request, quotes, rfqs, selection, approvals, vendors
    (by id), po, delivery, invoices. Anything missing simply produces no section."""
    sections = [s for s in _BUILDERS[key](d, staff) if s]
    if key in _OWN_TIMELINE:
        line = _timeline(d["events"], {_short(NAMES[key])}, staff)
        if line:
            sections.append(line)
    return {"key": key, "name": NAMES[key], "role": ROLES[key], "audience": "staff" if staff else "requester", "sections": sections}


# ---------------------------------------------------------------------------------------------
# "As it was at that moment": the same account, wound back to a time, for the replay.

_INVOICE_EVENT_STATUS = {"invoice.on_hold": "on_hold", "invoice.matched": "matched", "invoice.mismatch": "mismatch",
                         "invoice.approved": "approved", "invoice.rejected": "rejected"}


def as_of(d: dict, at) -> dict:
    """The gathered case data as it stood at `at` (naive UTC): later things are dropped, and anything that was
    later changed (a reply, a decision, a delivery) is shown in its earlier state. Never shows the future."""
    out = dict(d)
    events = [e for e in d["events"] if e["created_at"] <= at]
    out["events"] = events

    def seen(row, field="created_at"):
        return row.get(field) is None or row[field] <= at

    every = [q for q in d.get("quotes", []) + d.get("earlier_quotes", []) if seen(q)]
    out["quotes"] = [q for q in every if not q.get("superseded_at") or q["superseded_at"] > at]     # still counting at that moment
    out["earlier_quotes"] = [q for q in every if q.get("superseded_at") and q["superseded_at"] <= at]
    reminded = [e for e in events if e["event_type"] == "rfq.reminded"]
    rfqs = []
    for r in d.get("rfqs", []):
        if not seen(r, "sent_at"):
            continue
        r = dict(r)
        r["reminder_count"] = sum(1 for e in reminded if r["vendor_name"] in ((e.get("payload") or {}).get("vendors") or []))
        if r.get("replied_at") and r["replied_at"] > at:
            r.update(status="sent", replied_at=None)
        rfqs.append(r)
    out["rfqs"] = rfqs

    sel = d.get("selection")
    latest = next((e for e in reversed(events) if e["event_type"] == "vendor.selected"), None)
    if sel and latest:
        picked = (latest.get("payload") or {})
        vendor = (d.get("vendors") or {}).get(picked.get("vendor_id")) or {}
        out["selection"] = {**sel, "vendor_id": picked.get("vendor_id", sel["vendor_id"]),
                            "vendor_name": vendor.get("name") or sel["vendor_name"], "rationale": picked.get("rationale") or sel["rationale"]}
    else:
        out["selection"] = None

    approvals = []
    for a in d.get("approvals", []):
        if not seen(a):
            continue
        if a.get("decided_at") and a["decided_at"] > at:
            a = {**a, "status": "pending", "decided_by": None, "decided_at": None, "decision_note": None}
        approvals.append(a)
    out["approvals"] = approvals

    po = d.get("po")
    if po and not seen(po):
        po = None
    elif po and po.get("sent_at") and po["sent_at"] > at:
        po = {**po, "status": "issued", "sent_at": None}
    out["po"] = po

    dl = d.get("delivery")
    if dl and po is None:
        dl = None
    elif dl:
        chased = [e for e in events if e["event_type"] == "delivery.chased"]
        dl = {**dl, "chase_count": len(chased), "last_chased_at": chased[-1]["created_at"] if chased else None}
        if dl.get("escalated_at") and dl["escalated_at"] > at:
            dl["escalated_at"] = None
        if dl.get("delivered_at") and dl["delivered_at"] > at:
            dl.update(delivery_status="pending", delivered_at=None, received_by=None, delivery_note=None)
    out["delivery"] = dl

    invoices = []
    for inv in d.get("invoices", []):
        if not seen(inv):
            continue
        if inv.get("decided_at") and inv["decided_at"] > at:
            before = [e for e in events if e["event_type"] in _INVOICE_EVENT_STATUS and (e.get("payload") or {}).get("invoice_id") == inv["invoice_id"]
                      and e["event_type"] not in ("invoice.approved", "invoice.rejected")]
            inv = {**inv, "status": _INVOICE_EVENT_STATUS[before[-1]["event_type"]] if before else "mismatch",
                   "decided_by": None, "decided_at": None, "decision_note": None}
        invoices.append(inv)
    out["invoices"] = invoices
    return out
