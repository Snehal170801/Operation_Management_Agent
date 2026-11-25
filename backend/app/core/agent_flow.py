"""What each agent is doing for one case, worked out from where the case is and the step signals the
agents recorded (see agent_steps.py). Pure functions: no database, clock or network, so every rule
here is easy to test.

States of an agent on a case:
  pending       not reached yet
  working       a step is running right now (a step.started with no step.finished yet)
  waiting       did its part and is waiting on an outside party (suppliers, goods, an invoice)
  needs_person  stopped until a person decides or fixes something
  done          finished
  skipped       not needed for this case (e.g. enough stock, so no suppliers)
  stopped       the case ended here (a rejected approval)
  failed        its last attempt errored

Two audiences: "requester" (plain wording, nothing internal) and "staff" (more detail, errors).
"""

from datetime import date, datetime, timedelta

from app.core.agent_steps import FLOW_AGENTS, STEPS

# A step that started but never finished (the server was restarted mid-step) must not look busy forever.
STALE_AFTER = timedelta(minutes=10)

ROLE = {
    "Purchase Agent": "Reads your request",
    "Procurement Agent": "Checks stock",
    "Vendor Agent": "Gets and compares quotes",
    "Approval Agent": "Checks the order is approved",
    "PO Agent": "Places the order",
    "Delivery Agent": "Follows up on delivery",
    "Invoice Agent": "Checks the invoice",
}

DONE_NOTE = {
    "Purchase Agent": "Understood your request",
    "Procurement Agent": "Checked our stock",
    "Vendor Agent": "Chose a supplier",
    "Approval Agent": "Approved",
    "PO Agent": "Order sent to the supplier",
    "Delivery Agent": "Goods received",
    "Invoice Agent": "Invoice cleared",
}

# stage -> (index of the agent the case is at, that agent's state)
_AT = {
    "created": (0, "pending"),
    "purchase_request_created": (1, "pending"),
    "sourcing_needed": (2, "pending"),
    "awaiting_quotes": (2, "waiting"),
    "sourcing_stalled": (2, "needs_person"),
    "negotiating": (2, "waiting"),
    "vendor_selected": (3, "pending"),
    "awaiting_approval": (3, "needs_person"),
    "approved": (4, "pending"),
    "po_send_failed": (4, "needs_person"),
    "po_failed": (4, "needs_person"),
    "po_issued": (5, "waiting"),
    "delivery_late": (5, "needs_person"),
    "delivered": (6, "waiting"),
    "cancel_pending": (4, "waiting"),
}

# (agent, state, stage) -> (requester wording, staff wording)
_NOTES = {
    ("Vendor Agent", "waiting", "awaiting_quotes"): ("Waiting for suppliers to reply", "Waiting for supplier quotes"),
    ("Vendor Agent", "waiting", "negotiating"): ("Comparing the offers", "Asked the best supplier for a better price. Waiting for the answer."),
    ("Vendor Agent", "needs_person", "sourcing_stalled"): (
        "Taking longer than usual. Our team has been told.", "No supplier replied in time. Follow up with suppliers."),
    ("Approval Agent", "needs_person", "awaiting_approval"): (
        "Waiting for a manager's approval", "Waiting for approval. Open the Approvals page."),
    ("PO Agent", "needs_person", "po_send_failed"): (
        "Our team is finishing the order with the supplier", "The order could not be emailed. Fix the supplier's email and retry."),
    ("PO Agent", "needs_person", "po_failed"): (
        "Our team is finishing the order with the supplier", "The order could not be created automatically."),
    ("PO Agent", "waiting", "cancel_pending"): (
        "Cancelling the order with the supplier", "Waiting for the supplier to confirm the cancellation"),
    ("Delivery Agent", "waiting", "po_issued"): ("Waiting for the goods to arrive", "Waiting for delivery"),
    ("Delivery Agent", "needs_person", "delivery_late"): (
        "Running late. Our team is following up with the supplier.", "Overdue and the supplier has not responded. Contact them."),
    ("Invoice Agent", "waiting", "delivered"): ("Waiting for the supplier's invoice", "Waiting for the supplier's invoice"),
}

_HEADLINE = {
    "created": "We've received your request.",
    "purchase_request_created": "Checking whether we already have this in stock.",
    "sourcing_needed": "We don't have enough in stock, so we're asking suppliers for prices.",
    "awaiting_quotes": "We've asked suppliers for prices and are waiting for their replies.",
    "sourcing_stalled": "This is taking longer than usual. Our team has been told and will follow up.",
    "negotiating": "We have the offers and are checking whether the best supplier can do better.",
    "vendor_selected": "We've compared the quotes and chosen a supplier.",
    "awaiting_approval": "Waiting for a manager's approval.",
    "approved": "Approved. We are placing the order.",
    "po_send_failed": "Approved. Our team is finishing the order with the supplier.",
    "po_failed": "Approved. Our team is finishing the order with the supplier.",
    "po_issued": "The order has been placed. Waiting for delivery.",
    "delivery_late": "Delivery is running late. Our team is following up with the supplier.",
    "delivered": "Delivered. Waiting for the supplier's invoice.",
    "cancel_pending": "You cancelled this request. We have asked the supplier to cancel the order and are waiting for their answer.",
    "cancelled": "This request was cancelled.",
    "merged": "This request was combined with another request for the same item, so one order covers both.",
    "completed": "Delivered and paid up. This request is complete.",
    "fulfilled_from_stock": "Good news: it's in stock and will be dispatched to you.",
    "rejected": "This request wasn't approved. Please speak to your manager if you have questions.",
}
_HEADLINE_STAFF = {
    "sourcing_stalled": "No supplier quotes came in. A person needs to follow up.",
    "awaiting_approval": "Waiting for a person to approve the supplier selection.",
    "po_send_failed": "The purchase order could not be emailed. A person needs to fix and retry.",
    "po_failed": "The purchase order could not be created. A person needs to look.",
    "delivery_late": "Delivery is overdue and the supplier hasn't responded. A person needs to contact them.",
    "completed": "Goods received and the invoice cleared. Case complete.",
}

_RUN_ENDS = ("step.finished", "step.failed")

# Things that happen outside a tracked step but belong in the live feed: event -> (agent, wording, tone).
# Fixed wording only, so nothing here can leak a name, amount or reason to a requester.
_DOMAIN_FEED = {
    "vendor.selected": ("Vendor", "Chose a supplier", "ok"),
    "quote.declined": ("Vendor", "A supplier said they cannot supply, so the Vendor team was told", "warn"),
    "quote.no_price": ("Vendor", "A supplier replied without a price, so they were asked for one and the Vendor team was told", "warn"),
    "email.auto_reply": ("Vendor", "An automatic out-of-office reply arrived and was ignored", "info"),
    "sourcing.stalled": ("Vendor", "No supplier replied in time", "warn"),
    "approval.requested": ("Approval", "Sent for a person's decision", "warn"),
    "approval.auto_approved": ("Approval", "Approved automatically", "ok"),
    "approval.approved": ("Approval", "Approved by a manager", "ok"),
    "approval.rejected": ("Approval", "Not approved", "bad"),
    "approval.delegated": ("Approval", "The approver is on leave, so their backup was asked instead", "info"),
    "sourcing.restarted": ("Vendor", "The offers were turned down, so suppliers were asked again", "warn"),
    "po.issued": ("PO", "Order sent to the supplier", "ok"),
    "po.send_failed": ("PO", "The order could not be sent", "warn"),
    "po.confirmed": ("PO", "The supplier confirmed the order", "ok"),
    "po.returned_unchanged": ("PO", "The supplier sent our own order back with nothing added, so the PO desk was told", "warn"),
    "invoice.credit_note": ("Invoice", "The supplier sent a credit note, so Accounts was told", "warn"),
    "invoice.proforma": ("Invoice", "The supplier sent a proforma invoice (not a bill), so the final invoice was requested", "warn"),
    "invoice.final_requested": ("Invoice", "Asked the supplier for the final invoice", "info"),
    "po.confirmation_chased": ("PO", "Reminded the supplier to confirm the order", "info"),
    "po.confirmation_overdue": ("PO", "The supplier has not confirmed the order", "warn"),
    "po.vendor_problem": ("PO", "The supplier raised a problem with the order", "warn"),
    "po.problem_resolved": ("PO", "The problem with the order was sorted out", "ok"),
    "delivery.chased": ("Delivery", "Reminded the supplier about delivery", "info"),
    "delivery.escalated": ("Delivery", "Delivery is overdue", "warn"),
    "delivery.received": ("Delivery", "Goods received", "ok"),
    "request.changed": ("Purchase", "The request was changed", "info"),
    "case.merged_into": ("Case", "Combined with another request for the same item", "info"),
    "case.cancelled": ("Case", "The request was cancelled", "warn"),
    "rfq.withdrawn": ("Vendor", "Suppliers were told the request is withdrawn", "info"),
    "email.bounced": ("Notification", "An email to a supplier bounced, so they could not be reached", "warn"),
    "quote.refresh_requested": ("Vendor", "A supplier's quote had expired, so they were asked to refresh it", "warn"),
    "quote.revised": ("Vendor", "A supplier sent a revised price, so the choice was made again", "info"),
    "po.price_change_proposed": ("PO", "The supplier asked for a different price and an approver was asked", "warn"),
    "po.price_change_accepted": ("PO", "The revised price was accepted", "info"),
    "po.price_change_rejected": ("PO", "The revised price was refused", "warn"),
    "po.price_lowered": ("PO", "The supplier lowered the price", "ok"),
    "po.cancel_requested": ("PO", "The supplier was asked to cancel the order", "warn"),
    "po.cancel_refused": ("PO", "The supplier says the order cannot be cancelled", "warn"),
    "po.cancel_chased": ("PO", "Reminded the supplier about the cancellation", "info"),
    "po.cancel_overdue": ("PO", "The supplier has not answered the cancellation", "warn"),
    "po.cancelled": ("PO", "The order was cancelled", "ok"),
    "po.cancel_withdrawn": ("PO", "The cancellation was dropped and the order carries on", "info"),
    "po.change_requested": ("PO", "A change to the order was passed to the purchasing team", "info"),
    "po.change_handled": ("PO", "The change to the order was dealt with", "ok"),
    "goods.issue_reported": ("Delivery", "A problem with the goods was reported to the supplier", "warn"),
    "goods.issue_resolved": ("Delivery", "The problem with the goods was sorted out", "ok"),
    "goods.issue_chased": ("Delivery", "Reminded the supplier about the problem with the goods", "info"),
    "goods.issue_overdue": ("Delivery", "The supplier has not said how they will put the goods right", "warn"),
    "delivery.partial": ("Delivery", "Part of the order has arrived", "info"),
    "document.attached": ("Operations", "A supplier document was attached to this case by a person", "info"),
    "document.duplicate_file": ("Vendor", "The same file arrived again and was not read a second time", "info"),
    "document.received": ("Vendor", "A document arrived from the supplier", "info"),
    "document.reading": ("Vendor", "Reading the document", "info"),
    "document.read": ("Vendor", "Finished reading the document", "info"),
    "quote.question": ("Vendor", "A supplier asked a question before quoting, so the Vendor team was told", "warn"),
    "quote.partial": ("Vendor", "A quote seems to cover only some of the items, so the Vendor team was told", "warn"),
    "email.duplicate": ("Vendor", "The same email arrived again and was not handled twice", "info"),
    "document.unsupported_file": ("Vendor", "A file we cannot read came with an email, so the Vendor team was told", "warn"),
    "delivery.claimed_by_supplier": ("Delivery", "The supplier says the goods were delivered, so Receiving was asked to check", "warn"),
    "invoice.after_close": ("Invoice", "An invoice arrived after the request was closed, so Accounts was asked to check for a duplicate", "warn"),
    "approval.routed_to_admin": ("Approval", "No normal approver could be asked, so the admins were told", "warn"),
    "delivery.over_delivered": ("Delivery", "More arrived than was ordered, so Receiving and Accounts were told", "warn"),
    "delivery.before_confirmation": ("Delivery", "The goods arrived before the supplier had confirmed the order", "info"),
    "stock.returned": ("Stock", "The request was cancelled, so what it took from stock was put back", "info"),
    "case.owner_left": ("Operations", "The person who asked for this can no longer sign in, so the admins were told", "warn"),
    "approval.link_refused": ("Approval", "An approval link made for someone who can no longer approve was refused", "warn"),
    "goods.returned": ("Delivery", "The faulty goods were sent back to the supplier", "info"),
    "goods.replacement_expected": ("Delivery", "The supplier promised a replacement, so payment stays held until it arrives", "info"),
    "goods.replacement_received": ("Delivery", "The replacement arrived", "ok"),
    "goods.credit_logged": ("Delivery", "The supplier agreed a credit, so Accounts were told to apply it by hand", "info"),
    "negotiation.asked": ("Vendor", "The best supplier was asked for a better price", "info"),
    "negotiation.improved": ("Vendor", "The supplier offered a better price, which was taken", "ok"),
    "negotiation.no_improvement": ("Vendor", "The supplier did not offer a better price, so the original quote stands", "info"),
    "negotiation.no_reply": ("Vendor", "The supplier did not answer in time, so the original quote stands", "info"),
    "negotiation.skipped": ("Vendor", "The supplier could not be asked for a better price, so the original quote goes on", "info"),
    "document.unreadable": ("Vendor", "A document from the supplier could not be read, so a person was asked to look", "warn"),
    "document.resend_requested": ("Invoice", "The supplier was asked to resend a document we can read", "info"),
    "invoice.details_requested": ("Invoice", "The supplier was asked for the invoice details (number, order number, total)", "info"),
    "restock.requested": ("Purchase", "Stock was low, so more was ordered", "info"),
    "restock.auto_triggered": ("Purchase", "Stock reached its minimum, so a reorder started by itself and an approver must approve it", "info"),
    "stock.increased": ("Procurement", "The goods that arrived were added to stock", "ok"),
    "stock.topup_unmatched": ("Procurement", "Some goods that arrived match no stock item, so stock was not changed for them", "warn"),
    "stock.topup_failed": ("Procurement", "The goods that arrived could not be added to stock. Please update the stock by hand.", "warn"),
    "stock.reduced": ("Procurement", "The faulty goods were taken back off the stock count", "info"),
    "stock.reduce_unmatched": ("Procurement", "Some faulty goods match no stock item, so stock was not changed for them", "warn"),
    "rfq.preferred_unreachable": ("Vendor", "A preferred supplier could not be asked (no working e-mail address)", "warn"),
    "stock.restored": ("Procurement", "The goods were put back on the stock count", "ok"),
    "stock.restore_unmatched": ("Procurement", "Some goods match no stock item any more, so stock was not changed for them", "warn"),
    "stock.restore_failed": ("Procurement", "The goods could not be put back on the stock count. Please update the stock by hand.", "warn"),
    "stock.reduce_failed": ("Procurement", "The faulty goods could not be taken off the stock count. Please update the stock by hand.", "warn"),
    "delivery.short_closed": ("Delivery", "The rest of the order will not come, and that was accepted", "warn"),
    "delivery.requester_confirmed": ("Delivery", "The requester confirmed the goods reached them", "ok"),
    "delivery.requester_disputed": ("Delivery", "The requester says the goods have not reached them", "warn"),
    "delivery.dispute_handled": ("Delivery", "Receiving followed up on the missing goods", "info"),
    "invoice.on_hold": ("Invoice", "Invoice received. Waiting for the goods.", "info"),
    "invoice.matched": ("Invoice", "Invoice matched the order", "ok"),
    "invoice.mismatch": ("Invoice", "Invoice needs a closer look", "warn"),
    "invoice.rejected": ("Invoice", "Invoice not accepted", "warn"),
    "invoice.vendor_notified": ("Invoice", "The supplier was asked for a corrected invoice", "info"),
    "invoice.chased": ("Invoice", "Reminded the supplier to send a corrected invoice", "info"),
    "invoice.correction_overdue": ("Invoice", "The supplier still has not sent a corrected invoice", "warn"),
    "case.stuck": ("Operations", "The request has sat at one step too long, so the right department was told", "warn"),
    "case.stuck_escalated": ("Operations", "Still stuck, so the admin was told", "warn"),
    "escalation.sent": ("Notification", "Nobody had acted for a long time, so a senior person was told", "warn"),
    "case.closed": ("Case", "Request complete", "ok"),
}
ACTIVITY_LIMIT = 8

# Events with a plain-English line for STAFF only. A requester's feed skips them: they say what a supplier sent or why a person was
# told, which a requester must not see (no prices, supplier names or reasons).
STAFF_ONLY_FEED = frozenset({
    "negotiation.asked", "negotiation.improved", "negotiation.no_improvement", "negotiation.no_reply", "negotiation.skipped",
    "goods.returned", "goods.replacement_expected", "goods.replacement_received", "goods.credit_logged", "quote.declined", "quote.no_price", "quote.question", "quote.partial", "email.auto_reply", "email.duplicate", "email.bounced",
    "document.duplicate_file", "document.unsupported_file", "invoice.credit_note", "invoice.proforma", "invoice.final_requested",
    "invoice.after_close", "po.returned_unchanged", "delivery.claimed_by_supplier", "delivery.over_delivered", "delivery.before_confirmation",
    "approval.routed_to_admin", "approval.delegated", "approval.link_refused", "case.owner_left", "stock.returned", "quote.refresh_requested",
    "po.confirmation_overdue", "po.vendor_problem", "po.price_change_proposed", "po.price_change_accepted", "po.price_change_rejected",
})

# Everything else the app can record, in plain English, for the staff timeline. (Types that already have a line in _DOMAIN_FEED use that.)
EXTRA_LABELS = {
    "automation.held": "Automation was paused, so this request waits",
    "call.started": "A reminder call to the supplier was started",
    "call.notified": "A reminder call to the supplier was made",
    "call.skipped": "A reminder call to the supplier was skipped",
    "goods.supplier_replied": "The supplier replied about the goods problem",
    "invoice.matched": "The invoice matches the order",
    "invoice.mismatch": "The invoice does not match the order, so Accounts was told",
    "invoice.on_hold": "The invoice is on hold until the goods are confirmed",
    "invoice.rejected": "The invoice was rejected",
    "invoice.approved": "The invoice was approved",
    "invoice.vendor_notified": "The supplier was told about the invoice problem",
    "invoice.details_requested": "The supplier was asked for the invoice details",
    "notification.no_recipients": "Nobody with an e-mail address could be told",
    "notification.sent": "A person was told by e-mail",
    "po.error": "Something went wrong with the order, so a person was asked to look",
    "quote.email_ignored": "An e-mail was ignored (see the reason)",
    "rfq.reminded": "A silent supplier was reminded to quote",
    "sourcing.no_vendors": "There was no supplier to ask",
    "vendor.replied": "A supplier replied",
    "worker.error": "An automatic step failed, so a person was asked to look",
    "system.loop_restarted": "A background job had stopped and was started again",
    "combine.suggested": "Two requests for the same item could be combined, so the Vendor team was offered a single order",
    "combine.dismissed": "The suggestion to combine two requests was dismissed",
    "po.change_requested": "A change to the order was asked for, so the PO desk was told",
    "po.change_handled": "The change to the order was dealt with",
    "delivery.requester_confirmed": "The requester confirmed the goods arrived",
    "delivery.requester_disputed": "The requester says the goods did not arrive, so Receiving was told",
    "delivery.dispute_handled": "The dispute about the goods was dealt with",
}


def staff_label(event_type: str) -> str | None:
    """Plain English for one event on the staff timeline, or None when the page's own wording applies. Never for stage.* / step.* bookkeeping."""
    if event_type in _DOMAIN_FEED:
        return _DOMAIN_FEED[event_type][1]
    return EXTRA_LABELS.get(event_type)


# What comes after each agent, in plain fixed wording (safe for a requester: no names, amounts or reasons).
_NEXT = {
    "Purchase Agent": "The request will be read and split into items.",
    "Procurement Agent": "We'll check whether it is already in stock.",
    "Vendor Agent": "Suppliers will be asked for their prices.",
    "Approval Agent": "The order will be checked, and a person signs off if it needs one.",
    "PO Agent": "The order will be sent to the supplier.",
    "Delivery Agent": "We'll follow up until the goods arrive.",
    "Invoice Agent": "The supplier's invoice will be checked against the order.",
}


def next_step(nodes: list[dict], status: str) -> str | None:
    """What happens after the part that is under way now: the first agent after it that has not started.
    Nothing once the case is closed or nothing is left to do."""
    if status == "closed":
        return None
    active = [i for i, n in enumerate(nodes) if n["state"] in ("working", "waiting", "needs_person", "failed")]
    after = max(active[0] if active else -1, -1)
    upcoming = next((n for n in nodes[after + 1:] if n["state"] == "pending"), None)
    return _NEXT.get(upcoming["name"]) if upcoming else None


def build_support(events: list[dict], status: str, staff: bool) -> list[dict]:
    """The two agents that are not a stage in the line. Operations keeps the record of the whole case;
    Notification emails the people who can approve when a person is needed. Wording is fixed, so nothing
    here can show a requester an address, name or reason."""
    recorded = len(events)
    ops = {
        "key": "operations", "name": "Operations Agent", "role": "Keeps the record of this request",
        "state": "done" if status == "closed" else "active",
        "label": f"Closed the request · {recorded} steps recorded" if status == "closed" else f"Recording every step · {recorded} so far",
    }
    notes = [e for e in events if e["event_type"] in ("notification.sent", "notification.no_recipients")]
    sent = sum((e.get("payload") or {}).get("sent", 0) for e in notes if e["event_type"] == "notification.sent")
    failed = sum((e.get("payload") or {}).get("failed", 0) for e in notes if e["event_type"] == "notification.sent")
    silent = any(e["event_type"] == "notification.no_recipients" for e in notes)
    if silent or failed:
        state, label = "attention", ("Nobody could be reached" if silent else "Some emails did not go out")
    elif sent:
        state, label = "done", (f"Emailed {sent} {'person' if sent == 1 else 'people'} who can approve" if staff else "A person has been told")
    else:
        state, label = "idle", "Nothing needed yet"
    notify = {"key": "notification", "name": "Notification Agent", "role": "Tells a person when they are needed", "state": state, "label": label}
    return [ops, notify]


def apply_expected_delivery(flow: dict, expected: date | None, today: date) -> dict:
    """Put the delivery date on the Delivery agent while the goods are still awaited: "Expected by 7 Oct",
    or "Overdue: was due 7 Oct". Once the goods are in (or before an order exists) its words are left alone.
    The date is not sensitive, so a requester sees it too."""
    flow["expected_delivery"] = expected
    if expected is None:
        return flow
    delivery = next((n for n in flow["agents"] if n["key"] == "delivery"), None)
    if delivery and delivery["state"] in ("waiting", "needs_person"):
        when = f"{expected.day} {expected:%b}"
        delivery["label"] = f"Overdue: was due {when}" if today > expected else f"Expected by {when}"
    return flow


def agent_key(name: str) -> str:
    return name.split()[0].lower()


def headline_for(stage: str, status: str, staff: bool = False) -> str:
    """One sentence on where a case is, for the current stage."""
    return (_HEADLINE_STAFF.get(stage) if staff else None) or _HEADLINE.get(stage) or (
        "This request is complete." if status == "closed" else "Your request is in progress.")


def build_flow(case: dict, events: list[dict], audience: str, now: datetime) -> dict:
    """The full picture for one case. `case` needs stage and status; `events` are the case's events
    (oldest first); `audience` is "requester" or "staff"."""
    staff = audience == "staff"
    stage, status = case["stage"], case["status"]

    states = _baseline(stage, status, events)
    runs = _runs(events)
    _apply_invoice_signals(states, events, status)
    _apply_po_signals(states, events, status)
    _apply_goods_signals(states, events, status)
    nodes = []
    for i, name in enumerate(FLOW_AGENTS):
        agent_runs = [r for r in runs if STEPS[r["step"]].agent == name]
        open_run = next((r for r in reversed(agent_runs) if r["open"] and now - r["started_at"] <= STALE_AFTER), None)
        last_ended = next((r for r in reversed(agent_runs) if not r["open"]), None)

        state = states[i]
        if open_run:
            state = "working"
        elif state in ("pending", "waiting") and last_ended and last_ended["failed"]:
            state = "failed"

        nodes.append(_node(name, state, stage, agent_runs, open_run, last_ended, events, staff))

    result = _summary(case, nodes, stage, status, staff, now)
    result["activity"] = _activity(events, runs, staff)
    result["support"] = build_support(events, status, staff)
    return result


# ---------------------------------------------------------------------------------------------

def _baseline(stage: str, status: str, events: list[dict]) -> list[str]:
    n = len(FLOW_AGENTS)
    if stage == "fulfilled_from_stock":
        return ["done", "done"] + ["skipped"] * (n - 2)
    if stage == "rejected":
        return ["done", "done", "done", "stopped"] + ["skipped"] * (n - 4)
    if stage in ("cancelled", "merged"):
        at = min(_position_from_events(events)[0], n - 1)       # stopped where it had got to
        return ["done"] * at + ["stopped"] + ["skipped"] * (n - at - 1)
    if stage == "completed" or (status == "closed" and stage not in _AT):
        return ["done"] * n

    position = _AT.get(stage) or _position_from_events(events)
    index, state = position
    return ["done"] * index + [state] + ["pending"] * (n - index - 1)


def _position_from_events(events: list[dict]) -> tuple[int, str]:
    """For a stage this module does not know: continue after the furthest agent that finished a step."""
    furthest = -1
    for event in events:
        if event["event_type"] == "step.finished" and event["payload"] and event["payload"].get("step") in STEPS:
            furthest = max(furthest, FLOW_AGENTS.index(STEPS[event["payload"]["step"]].agent))
    return min(furthest + 1, len(FLOW_AGENTS) - 1), "pending"


_PO_UNRESOLVED = ("po.confirmation_overdue", "po.vendor_problem")
_PO_RESOLVED = ("po.confirmed", "po.problem_resolved")


def po_needs_person(events: list[dict]) -> bool:
    """The supplier raised a problem with the order, or never confirmed it after the reminders, and nobody has sorted it out."""
    last = next((e["event_type"] for e in reversed(events) if e["event_type"] in _PO_UNRESOLVED + _PO_RESOLVED), None)
    return last in _PO_UNRESOLVED


def _apply_po_signals(states: list[str], events: list[dict], status: str) -> None:
    """The order's own result can need a person while the case stage stays where it is (goods still awaited)."""
    i = FLOW_AGENTS.index("PO Agent")
    if (status == "open" and states[i] == "done" and po_needs_person(events)
            and not any(e["event_type"] == "delivery.received" for e in events)):
        states[i] = "needs_person"


def goods_issue_open(events: list[dict]) -> bool:
    """A problem with the goods was reported and not yet closed."""
    open_ids: set[str] = set()
    for e in events:
        p = e.get("payload") or {}
        if e["event_type"] == "goods.issue_reported":
            open_ids.add(p.get("issue_id"))
        elif e["event_type"] == "goods.issue_resolved":
            open_ids.discard(p.get("issue_id"))
    return bool(open_ids)


def _apply_goods_signals(states: list[str], events: list[dict], status: str) -> None:
    i = FLOW_AGENTS.index("Delivery Agent")
    if status == "open" and goods_issue_open(events) and states[i] in ("done", "waiting", "pending"):
        states[i] = "needs_person"


def _apply_invoice_signals(states: list[str], events: list[dict], status: str) -> None:
    """The invoice's own result can change the Invoice agent while the case stage stays where it is."""
    if status != "open":
        return
    last = next((e["event_type"] for e in reversed(events)
                 if e["event_type"] in ("invoice.matched", "invoice.mismatch", "invoice.on_hold",
                                        "invoice.approved", "invoice.rejected")), None)
    i = FLOW_AGENTS.index("Invoice Agent")
    if last == "invoice.mismatch" and states[i] in ("pending", "waiting"):
        states[i] = "needs_person"
    elif last in ("invoice.on_hold", "invoice.rejected") and states[i] == "pending":
        states[i] = "waiting"


def _runs(events: list[dict]) -> list[dict]:
    """Step events grouped into runs (one start, optional progress, optional end), oldest first."""
    by_run: dict[str, dict] = {}
    for e in events:
        payload = e.get("payload") or {}
        step = payload.get("step")
        if not e["event_type"].startswith("step.") or step not in STEPS:
            continue
        run = by_run.setdefault(payload.get("run") or f"x{e['event_id']}", {
            "step": step, "open": True, "failed": False, "started_at": e["created_at"], "ended_at": None,
            "seconds": None, "progress": None, "error": None, "detail": None})
        if e["event_type"] == "step.started":
            run["started_at"], run["detail"] = e["created_at"], payload.get("detail")
        elif e["event_type"] == "step.progress":
            run["progress"] = {"done": payload.get("done"), "total": payload.get("total"), "text": payload.get("text")}
        elif e["event_type"] in _RUN_ENDS:
            run.update(open=False, ended_at=e["created_at"], failed=e["event_type"] == "step.failed",
                       seconds=payload.get("seconds"), error=payload.get("error"))
    return list(by_run.values())


def _short(agent: str) -> str:
    return agent.replace(" Agent", "")


def _feed_line(e: dict, staff: bool) -> tuple[str, str, str] | None:
    """(agent, wording, tone) for one event that belongs in a live feed, or None. Fixed wording only."""
    payload = e.get("payload") or {}
    step = STEPS.get(payload.get("step")) if e["event_type"].startswith("step.") else None
    if step:
        agent, label = _short(step.agent), step.label.lower()
        if e["event_type"] == "step.started":
            return agent, step.label, "info"
        if e["event_type"] == "step.finished":
            took = payload.get("seconds")
            return agent, f"Finished: {label}" + (f" ({took:.1f} s)" if took else ""), "ok"
        if e["event_type"] == "step.failed":
            text = (f"Failed: {label}. {payload.get('error') or ''}".strip() if staff
                    else f"Ran into a problem: {label}. Our team has been told.")
            return agent, text, "bad"
        return None  # step.progress is shown on the agent itself, not as a line
    if e["event_type"] == "approval.rejected" and payload.get("re_sourcing"):
        return "Approval", "Offers turned down, new quotes will be asked for", "warn"
    if e["event_type"] in STAFF_ONLY_FEED and not staff:
        return None
    if e["event_type"] in _DOMAIN_FEED:
        return _DOMAIN_FEED[e["event_type"]]
    return None


def _activity(events: list[dict], runs: list[dict], staff: bool) -> list[dict]:
    """The latest things that happened, newest first: agents starting and finishing steps, plus the main
    hand-offs (approval, order sent, goods received...). Safe wording for requesters."""
    items = [(e, line) for e in events if (line := _feed_line(e, staff))]
    newest_first = sorted(items, key=lambda i: i[0]["event_id"], reverse=True)[:ACTIVITY_LIMIT]
    return [{"id": e["event_id"], "at": e["created_at"], "agent": agent, "text": text, "tone": tone}
            for e, (agent, text, tone) in newest_first]


def build_board_feed(events: list[dict], limit: int = 14) -> list[dict]:
    """The latest things the agents did across ALL cases (staff only), newest first. `events` carry case_id
    and case_number alongside the usual event fields."""
    items = [(e, line) for e in events if (line := _feed_line(e, True))]
    newest_first = sorted(items, key=lambda i: i[0]["event_id"], reverse=True)[:limit]
    return [{"id": e["event_id"], "at": e["created_at"], "case_id": e["case_id"], "case_number": e.get("case_number"),
             "agent": agent, "text": text, "tone": tone} for e, (agent, text, tone) in newest_first]


def _note(name: str, state: str, stage: str, staff: bool, events: list[dict]) -> str:
    if state == "pending":
        return ROLE[name]
    if state == "skipped":
        return "Not needed"
    if state == "stopped":
        return "Cancelled" if stage == "cancelled" else "Combined" if stage == "merged" else "Not approved"
    if state == "failed":
        return "A step failed. Check the details." if staff else "Something went wrong. Our team has been told."
    if state == "done":
        if name == "Approval Agent" and any(e["event_type"] == "approval.auto_approved" for e in events):
            return "Approved automatically"
        return DONE_NOTE[name]
    if name == "Delivery Agent" and state == "needs_person" and goods_issue_open(events):
        return "A problem with the goods is open. Follow it up with the supplier." if staff else "There is a problem with the delivery. Our team is sorting it out with the supplier."
    if name == "PO Agent" and state == "needs_person":
        problem = next((e["event_type"] for e in reversed(events) if e["event_type"] in _PO_UNRESOLVED + _PO_RESOLVED), "") == "po.vendor_problem"
        if staff:
            return "The supplier raised a problem with the order. Read their reply." if problem else "The supplier has not confirmed the order. Contact them."
        return "Our team is confirming the order with the supplier"
    if name == "Invoice Agent" and state == "needs_person":
        return "The invoice doesn't match the order. Review it." if staff else "Our team is checking the paperwork"
    if name == "Invoice Agent" and state == "waiting" and stage != "delivered":
        return "Invoice received. Waiting for the goods." if any(
            e["event_type"] == "invoice.on_hold" for e in events) else "Waiting for a corrected invoice"
    wording = _NOTES.get((name, state, stage))
    if wording:
        return wording[1] if staff else wording[0]
    return "Waiting" if state == "waiting" else ROLE[name]


def _node(name, state, stage, agent_runs, open_run, last_ended, events, staff) -> dict:
    live = open_run or None
    node = {
        "key": agent_key(name),
        "name": name,
        "role": ROLE[name],
        "state": state,
        "label": STEPS[live["step"]].label if live else _note(name, state, stage, staff, events),
        "progress": None,
        "started_at": min((r["started_at"] for r in agent_runs), default=None),
        "finished_at": max((r["ended_at"] for r in agent_runs if r["ended_at"]), default=None),
        "seconds": round(sum(r["seconds"] or 0 for r in agent_runs), 1) if agent_runs else None,
        "runs": len(agent_runs),
        "detail": None,
        "error": None,
    }
    if live and live["progress"] and live["progress"]["total"]:
        node["progress"] = live["progress"] if staff else {**live["progress"], "text": None}
    if staff:
        node["detail"] = (live or last_ended or {}).get("detail")
        if state == "failed" and last_ended:
            node["error"] = last_ended["error"]
    return node


def _summary(case: dict, nodes: list[dict], stage: str, status: str, staff: bool, now: datetime) -> dict:
    working = next((n for n in nodes if n["state"] == "working"), None)
    needs_person = [n for n in nodes if n["state"] == "needs_person"]
    focus = working or next((n for n in nodes if n["state"] in ("needs_person", "waiting", "failed")), None)

    if working:
        text = working["label"]
        if working["progress"]:
            text += f" ({working['progress']['done']} of {working['progress']['total']})"
        headline = f"{text}…"
    else:
        headline = headline_for(stage, status, staff)

    if stage == "fulfilled_from_stock":
        outcome = "fulfilled"
    elif stage == "rejected":
        outcome = "rejected"
    elif stage == "cancelled":
        outcome = "cancelled"
    elif stage == "merged":
        outcome = "merged"
    elif status == "closed":
        outcome = "completed"
    elif needs_person:
        outcome = "needs_person"
    else:
        outcome = "active"

    return {
        "case_id": case["case_id"],
        "stage": stage,
        "status": status,
        "outcome": outcome,
        "headline": headline,
        "active_agent": focus["name"] if focus else None,
        "needs_person": bool(needs_person),
        "agents": nodes,
        "next_step": next_step(nodes, status),
        "support": [],
        "generated_at": now,
        "audience": "staff" if staff else "requester",
    }


# ---------------------------------------------------------------------------------------------
# Admin live board: what every agent is doing across all open cases

_BOARD_STATES = ("needs_person", "failed", "working", "waiting")  # busiest / most urgent first
BOARD_CASES_PER_AGENT = 12


def build_board(entries: list[tuple[dict, dict]], now: datetime, feed: list[dict] | None = None) -> dict:
    """`entries` is (case summary, its staff flow) for each OPEN case. Returns one column per agent with
    how many cases it is working on / waiting on / blocked on, and the cases themselves (most urgent first)."""
    columns = []
    for i, name in enumerate(FLOW_AGENTS):
        cases = []
        for case, flow in entries:
            node = flow["agents"][i]
            if node["state"] in _BOARD_STATES:
                cases.append({
                    "case_id": case["case_id"], "case_number": case.get("case_number"), "items_summary": case.get("items_summary"),
                    "requester": case.get("requester_id"), "state": node["state"], "label": node["label"],
                    "progress": node["progress"],
                })
        cases.sort(key=lambda c: _BOARD_STATES.index(c["state"]))
        count = lambda s: sum(1 for c in cases if c["state"] == s)  # noqa: E731
        columns.append({
            "key": agent_key(name), "name": name, "role": ROLE[name],
            "working": count("working"), "waiting": count("waiting"),
            "needs_person": count("needs_person") + count("failed"),
            "now_doing": next((c["label"] for c in cases if c["state"] == "working"), None),
            "cases": cases[:BOARD_CASES_PER_AGENT], "more": max(0, len(cases) - BOARD_CASES_PER_AGENT),
        })
    return {
        "generated_at": now,
        "open_cases": len(entries),
        "working_now": sum(c["working"] for c in columns),
        "needs_person": sum(1 for _, f in entries if f["needs_person"]),
        "agents": columns,
        "feed": feed or [],
    }


# ---------------------------------------------------------------------------------------------
# Replay: how the case looked after each moment, so the page can play its story back

REPLAY_MAX_FRAMES = 150


def build_replay(case: dict, events: list[dict], audience: str) -> dict:
    """One frame per visible moment (an agent starting/finishing/progressing, or a hand-off), each holding the
    full picture at that moment, built with the SAME rules as the live page. The stage at a moment is rebuilt
    from the 'stage.*' bookkeeping events, so this works for every case, including old ones."""
    frames = []
    stage, status = "created", "open"
    i = 0
    while i < len(events):
        e = events[i]
        i += 1
        if e["event_type"].startswith("stage."):
            stage = e["event_type"][len("stage."):]
        elif e["event_type"] == "case.closed":
            status = "closed"
            stage = (e.get("payload") or {}).get("stage") or stage
        visible = e["event_type"].startswith("step.") or e["event_type"] in _DOMAIN_FEED
        if not visible:
            continue
        # the stage is written just AFTER the event that causes it: take it in before drawing the moment
        while i < len(events) and (events[i]["event_type"].startswith("stage.") or events[i]["event_type"] == "case.closed"):
            n = events[i]
            if n["event_type"] == "case.closed":
                status = "closed"
                stage = (n.get("payload") or {}).get("stage") or stage
            else:
                stage = n["event_type"][len("stage."):]
            i += 1
        flow = build_flow({"case_id": case["case_id"], "stage": stage, "status": status}, events[:i], audience, e["created_at"])
        frames.append({
            "at": e["created_at"],
            "headline": flow["headline"],
            "next_step": flow["next_step"],
            "support": flow["support"],
            "outcome": flow["outcome"],
            "agents": flow["agents"],
            "event": flow["activity"][0] if flow["activity"] else None,
        })

    if len(frames) > REPLAY_MAX_FRAMES:  # evenly thin out a very long story, always keeping the last frame
        step = len(frames) / REPLAY_MAX_FRAMES
        frames = [frames[int(n * step)] for n in range(REPLAY_MAX_FRAMES - 1)] + [frames[-1]]
    return {"case_id": case["case_id"], "audience": audience, "frames": frames}
