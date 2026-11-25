import json
import logging
import uuid
from datetime import date, timedelta

from app.agents import operations_agent
from app.clients import azure_openai_client, email_client
from app.core import change_policy, price_change, tax
from app.core.config import settings
from app.core.email_parsing import make_subject
from app.core.exceptions import InvalidInput, PurchaseOrderNotFound
from app.repositories import purchase_order_repository

logger = logging.getLogger(__name__)


def create_and_send(case_id: str, vendor: dict, quote: dict | None, items: list[dict]) -> dict:
    """Create the purchase order for the approved vendor and email it to them.
    The caller supplies the vendor, their chosen quote and the items (agents don't call each other)."""
    operations_agent.report_progress(1, 3, "Creating the order")
    lead_time = quote["lead_time_days"] if quote else None
    expected = date.today() + timedelta(days=lead_time) if lead_time else None

    purchase_order_repository.insert_purchase_order(
        str(uuid.uuid4()), case_id, vendor["vendor_id"],
        quote["price"] if quote else None, lead_time,
        quote["terms"] if quote else None, expected, items,
        tax=tax.lines(quote["price"] if quote else None, settings.TAX_RATE_PCT, settings.TAX_INCLUDED_IN_QUOTES),
    )
    return resend(case_id, vendor)


def resend(case_id: str, vendor: dict) -> dict:
    """(Re)email the case's existing PO to the vendor and record the outcome.
    Used on first send and when a failed send is retried (e.g. after adding the vendor's email)."""
    po = get_purchase_order(case_id)
    operations_agent.report_progress(2, 3, "Emailing the order to the supplier")

    status = "send_failed"
    if vendor.get("email"):
        try:
            email_client.send_email(
                vendor["email"], make_subject(case_id, f"Purchase Order {po['po_number']}"), _po_body(po),
            )
            status = "sent"
        except Exception:
            logger.exception("%s email to %s failed", po["po_number"], vendor["name"])
    purchase_order_repository.update_status(po["purchase_order_id"], status)
    operations_agent.report_progress(3, 3, "Order sent" if status == "sent" else "The order could not be emailed")

    operations_agent.publish_event(
        case_id, "po.issued" if status == "sent" else "po.send_failed", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "vendor": vendor["name"],
                 "total_amount": po["total_amount"], "status": status},
    )
    return get_purchase_order(case_id)


def get_purchase_order(case_id: str) -> dict:
    row = purchase_order_repository.find_purchase_order_by_case_id(case_id)
    if row is None:
        raise PurchaseOrderNotFound(case_id)
    return _row_to_dict(row)


def find_case_for_po_number(po_number: int, vendor_email: str) -> str | None:
    """The case behind order PO-<po_number>, if `vendor_email` is that order's supplier."""
    return purchase_order_repository.find_case_id_by_po_number_and_vendor_email(po_number, vendor_email)


def list_purchase_orders() -> list[dict]:
    return [_row_to_dict(r) for r in purchase_order_repository.find_all()]


def find_purchase_order(case_id: str) -> dict | None:
    row = purchase_order_repository.find_purchase_order_by_case_id(case_id)
    return _row_to_dict(row) if row else None


def _po_body(po: dict) -> str:
    lines = "\n".join(f"  - {i['description']} x {i['quantity']}" for i in po["items"])
    order_tax = tax.of_order(po)
    total = (f"{po['total_amount']:,.2f}" if po["total_amount"] is not None else "as per your quotation") if order_tax is None else \
        f"{order_tax['subtotal']:,.2f} + tax {order_tax['tax_amount']:,.2f} ({order_tax['rate_pct']:g}%) = {order_tax['total_with_tax']:,.2f} with tax"
    delivery = f"{po['expected_delivery_date']:%d %b %Y}" if po["expected_delivery_date"] else "as per your quotation"
    terms = po["terms"] or "as per your quotation"
    return (
        f"Dear {po['vendor_name']},\n\n"
        f"Further to your quotation, please find our purchase order {po['po_number']}.\n\n"
        f"Items:\n{lines}\n\n"
        f"Total amount: {total}\n"
        f"Delivery by: {delivery}\n"
        f"Terms: {terms}\n\n"
        f"Please confirm receipt of this order by replying to this email. Quote {po['po_number']} "
        f"on all invoices and delivery documents.\n\nThank you."
    )


def _row_to_dict(row) -> dict:
    return {
        "purchase_order_id": str(row.purchase_order_id),
        "po_number": f"PO-{row.po_number}",
        "case_id": str(row.case_id),
        "vendor_id": str(row.vendor_id),
        "vendor_name": row.vendor_name,
        "total_amount": float(row.total_amount) if row.total_amount is not None else None,
        "tax_rate_pct": float(getattr(row, "tax_rate_pct", None)) if getattr(row, "tax_rate_pct", None) is not None else None,
        "tax_amount": float(getattr(row, "tax_amount", None)) if getattr(row, "tax_amount", None) is not None else None,
        "total_with_tax": float(getattr(row, "total_with_tax", None)) if getattr(row, "total_with_tax", None) is not None else None,
        "lead_time_days": row.lead_time_days,
        "terms": row.terms,
        "expected_delivery_date": row.expected_delivery_date,
        "items": json.loads(row.items_json),
        "status": row.status,
        "created_at": row.created_at,
        "sent_at": row.sent_at,
        # whether the supplier has confirmed the order (getattr: rows from before the confirmation columns exist)
        "acknowledged_at": getattr(row, "acknowledged_at", None),
        "acknowledged_by": getattr(row, "acknowledged_by", None),
        "confirm_chase_count": getattr(row, "confirm_chase_count", 0) or 0,
        "last_confirm_chase_at": getattr(row, "last_confirm_chase_at", None),
        "confirm_escalated_at": getattr(row, "confirm_escalated_at", None),
        "vendor_issue": getattr(row, "vendor_issue", None),
        "vendor_email": getattr(row, "vendor_email", None),
        "cancel_requested_at": getattr(row, "cancel_requested_at", None),
        "cancel_requested_by": getattr(row, "cancel_requested_by", None),
        "cancel_reason": getattr(row, "cancel_reason", None),
        "cancel_chase_count": getattr(row, "cancel_chase_count", 0) or 0,
        "last_cancel_chase_at": getattr(row, "last_cancel_chase_at", None),
        "cancel_escalated_at": getattr(row, "cancel_escalated_at", None),
        "cancel_refused_at": getattr(row, "cancel_refused_at", None),
    }


# ---------------------------------------------------------------------------------------------
# Does the supplier confirm the order? (core/po_confirm_policy.py decides when to chase)

REPLY_PROMPT = """You are the PO Agent. A supplier replied to a purchase order we sent them. Decide what the reply is.
Return JSON: {"kind": "confirmed" | "problem" | "other", "issue": string | null, "new_price": number | null}
- confirmed: they accept the order, acknowledge receiving it, or say they will deliver as ordered (polite extras are fine).
- problem: they refuse, say they cannot supply, or want a different price, quantity, item or delivery date, or ask for changes.
- other: anything else (a question, small talk, an out-of-office, an invoice).
"issue" is one short sentence saying what the problem is, only when kind is "problem"; otherwise null.
"new_price" is the TOTAL price for the whole order in rupees as a plain number, only if they state a different total than before
(for example "the price is now 30,000"); otherwise null. Never guess it from a unit price."""


def classify_reply(text: str) -> dict:
    """What a supplier's reply to the order means: {"kind": confirmed | problem | other, "issue": str | None}.
    Never raises: if the AI is unavailable the reply is simply treated as "other" (a person can still read it)."""
    try:
        result = azure_openai_client.ask_json(REPLY_PROMPT, text[:3000])
    except Exception:
        logger.exception("could not classify the supplier's reply to the order")
        return {"kind": "other", "issue": None, "new_price": None}
    kind = result.get("kind") if isinstance(result, dict) else None
    issue = str(result.get("issue") or "").strip()[:300] or None if isinstance(result, dict) else None
    new_price = price_change.clean_price(result.get("new_price")) if isinstance(result, dict) else None
    return {"kind": kind if kind in ("confirmed", "problem") else "other", "issue": issue if kind == "problem" else None, "new_price": new_price}


def get_unconfirmed() -> list[dict]:
    """Emailed orders still waiting for the supplier to confirm (for the worker)."""
    return [{**_row_to_dict(r), "case_id": str(r.case_id)} for r in purchase_order_repository.find_unconfirmed()]


def acknowledge(case_id: str, *, via: str, by: str | None = None, sender: str | None = None, note: str | None = None) -> bool:
    """Record that the order is confirmed. `via` is email | invoice | person. False if it was already confirmed."""
    po = get_purchase_order(case_id)
    if not purchase_order_repository.mark_acknowledged(po["purchase_order_id"], by or sender):
        return False
    operations_agent.publish_event(
        case_id, "po.confirmed", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "via": via, "by": by, "from": sender, "note": note},
    )
    return True


def chase_confirmation(po: dict) -> bool:
    """Email the supplier again, asking them to confirm the order. False (and nothing recorded) if there is no address or it failed."""
    if not po.get("vendor_email"):
        return False
    body = (f"Dear {po['vendor_name']},\n\nWe sent you purchase order {po['po_number']} and have not yet had your confirmation. "
            f"Please reply to this email to confirm that you have received it and will deliver as ordered, "
            f"or tell us if there is a problem.\n\nThank you.")
    try:
        email_client.send_email(po["vendor_email"], make_subject(po["case_id"], f"Purchase Order {po['po_number']} - please confirm"), body)
    except Exception:
        logger.exception("Confirmation reminder for %s to %s failed", po["po_number"], po["vendor_name"])
        return False
    purchase_order_repository.mark_confirm_chased(po["purchase_order_id"])
    operations_agent.publish_event(
        po["case_id"], "po.confirmation_chased", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "number": po["confirm_chase_count"] + 1},
    )
    return True


def ask_what_was_meant(po: dict) -> bool:
    """The supplier sent our own order back with nothing added: ask what they needed (a confirmation? a price? a question?).
    False (nothing sent) if there is no address or sending failed."""
    if not po.get("vendor_email"):
        return False
    body = (f"Dear {po['vendor_name']},\n\nWe received back a copy of our own purchase order {po['po_number']}, with nothing added, so we are "
            f"not sure what you meant. Please reply in the body of this email to say whether you confirm the order as it stands, "
            f"or what you need from us (a change, a question, or your invoice).\n\nThank you.")
    try:
        email_client.send_email(po["vendor_email"], make_subject(po["case_id"], f"Purchase Order {po['po_number']} - what do you need?"), body)
    except Exception:
        logger.exception("Could not ask %s what they meant about %s", po["vendor_name"], po["po_number"])
        return False
    return True


def mark_confirmation_overdue(po: dict) -> None:
    purchase_order_repository.mark_confirm_escalated(po["purchase_order_id"])
    operations_agent.publish_event(
        po["case_id"], "po.confirmation_overdue", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "reminders": po["confirm_chase_count"]},
    )


def record_vendor_problem(case_id: str, issue: str | None, snippet: str, sender: str) -> None:
    """The supplier replied that something is wrong with the order. Kept until a person confirms it is sorted out."""
    po = get_purchase_order(case_id)
    purchase_order_repository.set_vendor_issue(po["purchase_order_id"], issue or "The supplier raised a problem with the order.")
    operations_agent.publish_event(
        case_id, "po.vendor_problem", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "issue": issue, "snippet": snippet[:300], "from": sender},
    )


def clear_vendor_issue(case_id: str, resolved_by: str, note: str | None) -> None:
    """A person says the problem the supplier raised has been sorted out."""
    po = get_purchase_order(case_id)
    purchase_order_repository.set_vendor_issue(po["purchase_order_id"], None)
    operations_agent.publish_event(
        case_id, "po.problem_resolved", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "by": resolved_by, "note": note},
    )


def get_confirmation_alerts() -> list[dict]:
    """Orders where a person is needed: the supplier raised a problem, or never confirmed after the reminders."""
    out = []
    for po in get_unconfirmed():
        if po["vendor_issue"]:
            out.append({**po, "kind": "problem"})
        elif po["confirm_escalated_at"] and not po["acknowledged_at"]:
            out.append({**po, "kind": "overdue"})
    for po in get_cancelling():
        if po["cancel_refused_at"]:
            out.append({**po, "kind": "cancel_refused"})
        elif po["cancel_escalated_at"]:
            out.append({**po, "kind": "cancel_overdue"})
    latest: dict[str, dict] = {}
    for e in operations_agent.get_events_of_types((change_policy.CHANGE_REQUESTED, change_policy.CHANGE_HANDLED)):
        latest[e["case_id"].lower()] = e                    # oldest first, so the last one wins
    for case_id, e in latest.items():
        if e["event_type"] == change_policy.CHANGE_REQUESTED:
            p = e.get("payload") or {}
            out.append({"kind": "change", "case_id": case_id, "po_number": p.get("po_number"), "vendor_name": p.get("vendor"),
                        "changes": p.get("changes", []), "by": p.get("by"), "note": p.get("note"), "sent_at": e["created_at"],
                        "confirm_escalated_at": None, "confirm_chase_count": 0, "vendor_issue": None})
    return out


# ---------------------------------------------------------------------------------------------
# Cancelling an order the supplier already has

CANCEL_REPLY_PROMPT = """You are the PO Agent. We asked a supplier to CANCEL a purchase order. Decide what their reply means.
Return JSON: {"kind": "agreed" | "refused" | "other"}
- agreed: they cancel it, agree to cancel, or say it is cancelled / no problem.
- refused: they say it cannot be cancelled (already made, shipped, dispatched, custom, or a cancellation charge applies).
- other: a question, an out-of-office, or anything not clearly yes or no."""


def classify_cancel_reply(text: str) -> str:
    """"agreed" | "refused" | "other". Never raises: if the AI is unavailable the reply is left for a person ("other")."""
    try:
        result = azure_openai_client.ask_json(CANCEL_REPLY_PROMPT, text[:3000])
    except Exception:
        logger.exception("could not classify the supplier's reply to the cancellation")
        return "other"
    kind = result.get("kind") if isinstance(result, dict) else None
    return kind if kind in ("agreed", "refused") else "other"


def request_cancellation(case_id: str, by: str, reason: str | None) -> dict:
    """Ask the supplier to cancel the emailed order, and stop chasing them for delivery or confirmation meanwhile.
    The email is a request, not a fact: the order stays live until they agree (or a person settles it)."""
    po = get_purchase_order(case_id)
    if not purchase_order_repository.mark_cancel_requested(po["purchase_order_id"], by, reason):
        raise InvalidInput("A cancellation has already been asked for on this order, or the goods have arrived.")
    sent = False
    if po.get("vendor_email"):
        why = f" Reason: {reason}." if reason else ""
        body = (f"Dear {po['vendor_name']},\n\nWe need to cancel purchase order {po['po_number']}.{why}\n\n"
                f"Please reply to confirm that the order is cancelled and nothing will be dispatched, or tell us if that is not possible.\n\nThank you.")
        try:
            email_client.send_email(po["vendor_email"], make_subject(case_id, f"Purchase Order {po['po_number']} - CANCELLATION"), body)
            sent = True
        except Exception:
            logger.exception("Cancellation email for %s to %s failed", po["po_number"], po["vendor_name"])
    operations_agent.publish_event(
        case_id, "po.cancel_requested", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "by": by, "reason": reason, "emailed": sent},
    )
    return get_purchase_order(case_id)


def chase_cancellation(po: dict) -> bool:
    if not po.get("vendor_email"):
        return False
    body = (f"Dear {po['vendor_name']},\n\nWe asked you to cancel purchase order {po['po_number']} and have not had your answer. "
            f"Please reply to confirm it is cancelled, or tell us if that is not possible.\n\nThank you.")
    try:
        email_client.send_email(po["vendor_email"], make_subject(po["case_id"], f"Purchase Order {po['po_number']} - CANCELLATION reminder"), body)
    except Exception:
        logger.exception("Cancellation reminder for %s failed", po["po_number"])
        return False
    purchase_order_repository.mark_cancel_chased(po["purchase_order_id"])
    operations_agent.publish_event(po["case_id"], "po.cancel_chased", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "number": po["cancel_chase_count"] + 1})
    return True


def mark_cancellation_overdue(po: dict) -> None:
    purchase_order_repository.mark_cancel_escalated(po["purchase_order_id"])
    operations_agent.publish_event(po["case_id"], "po.cancel_overdue", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "reminders": po["cancel_chase_count"]})


def record_cancellation_refused(case_id: str, snippet: str, sender: str) -> None:
    po = get_purchase_order(case_id)
    purchase_order_repository.mark_cancel_refused(po["purchase_order_id"])
    operations_agent.publish_event(case_id, "po.cancel_refused", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "snippet": snippet[:300], "from": sender})


def mark_cancelled(case_id: str) -> None:
    """The order is cancelled (the supplier agreed, or a person settled it): it no longer counts."""
    po = get_purchase_order(case_id)
    purchase_order_repository.update_status(po["purchase_order_id"], "cancelled")
    operations_agent.publish_event(case_id, "po.cancelled", agent_name="PO Agent", payload={"po_number": po["po_number"], "vendor": po["vendor_name"]})


def withdraw_cancellation(case_id: str, by: str, note: str | None) -> dict:
    """Carry on with the order after all: the cancellation request is dropped."""
    po = get_purchase_order(case_id)
    purchase_order_repository.clear_cancel_request(po["purchase_order_id"])
    operations_agent.publish_event(case_id, "po.cancel_withdrawn", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "by": by, "note": note})
    return get_purchase_order(case_id)


def get_cancelling() -> list[dict]:
    return [{**_row_to_dict(r), "case_id": str(r.case_id)} for r in purchase_order_repository.find_cancelling()]


def record_change_request(case_id: str, changes: list[dict], by: str, note: str | None) -> None:
    po = get_purchase_order(case_id)
    operations_agent.publish_event(
        case_id, "po.change_requested", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "changes": changes, "by": by, "note": note},
    )


def apply_change(case_id: str, changes: list[dict], total_amount, by: str, note: str | None) -> dict:
    """The change was agreed with the supplier: the order carries the new quantities (and total, if given)."""
    po = get_purchase_order(case_id)
    wanted = {c["item"].lower(): c["to"] for c in changes}
    items = [{**i, "quantity": wanted.get(i["description"].lower(), i["quantity"])} for i in po["items"]]
    purchase_order_repository.update_items_and_total(po["purchase_order_id"], items, total_amount)
    operations_agent.publish_event(case_id, CHANGE_HANDLED_EVENT, agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "outcome": "amended", "by": by, "note": note,
                                            "total_amount": total_amount})
    return get_purchase_order(case_id)


def decline_change(case_id: str, by: str, note: str | None) -> None:
    po = get_purchase_order(case_id)
    operations_agent.publish_event(case_id, CHANGE_HANDLED_EVENT, agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "outcome": "declined", "by": by, "note": note})


CHANGE_HANDLED_EVENT = "po.change_handled"


# ---------------------------------------------------------------------------------------------
# A supplier changes the price after the order

def record_price_proposal(case_id: str, new_total: float, pct: float, approval_id: str, snippet: str, sender: str) -> None:
    """The supplier asks for a higher price. Reminders stop (a person has it) and nothing about the order changes yet."""
    po = get_purchase_order(case_id)
    purchase_order_repository.set_vendor_issue(
        po["purchase_order_id"], f"Asks ₹{new_total:,.0f} instead of ₹{po['total_amount']:,.0f} (up {pct:g}%). Waiting for an approver.")
    operations_agent.publish_event(
        case_id, "po.price_change_proposed", agent_name="PO Agent",
        payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "old_total": po["total_amount"], "new_total": new_total,
                 "pct": pct, "approval_id": approval_id, "snippet": snippet[:300], "from": sender},
    )


def proposed_price(case_id: str, approval_id: str) -> dict | None:
    """The price the supplier asked for in the question an approver is deciding."""
    for e in reversed(operations_agent.get_case_events(case_id)):
        p = e.get("payload") or {}
        if e["event_type"] == "po.price_change_proposed" and p.get("approval_id") == approval_id:
            return p
    return None


def _set_total(po: dict, new_total: float) -> None:
    purchase_order_repository.update_items_and_total(po["purchase_order_id"], po["items"], new_total)


def apply_lower_price(case_id: str, new_total: float, old_total: float) -> None:
    po = get_purchase_order(case_id)
    _set_total(po, new_total)
    operations_agent.publish_event(case_id, "po.price_lowered", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "old_total": old_total, "new_total": new_total})


def apply_price_change(case_id: str, new_total: float, by: str, note: str | None) -> dict:
    """An approver accepted the higher price: the order total changes and the supplier is told we accept."""
    po = get_purchase_order(case_id)
    old_total = po["total_amount"]
    _set_total(po, new_total)
    purchase_order_repository.set_vendor_issue(po["purchase_order_id"], None)
    if po.get("vendor_email"):
        try:
            email_client.send_email(
                po["vendor_email"], make_subject(case_id, f"Purchase Order {po['po_number']} - revised price accepted"),
                f"Dear {po['vendor_name']},\n\nWe accept the revised total of {new_total:,.2f} for purchase order {po['po_number']}. "
                f"Please confirm and deliver as ordered.\n\nThank you.")
        except Exception:
            logger.exception("Price acceptance email for %s failed", po["po_number"])
    operations_agent.publish_event(case_id, "po.price_change_accepted", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "old_total": old_total, "new_total": new_total, "by": by, "note": note})
    return get_purchase_order(case_id)


def reject_price_change(case_id: str, asked_total: float, by: str, note: str | None) -> None:
    """An approver refused the higher price: the supplier is asked to honour the agreed price (or cancel), and a person follows up."""
    po = get_purchase_order(case_id)
    purchase_order_repository.set_vendor_issue(
        po["purchase_order_id"], f"We refused ₹{asked_total:,.0f}. Waiting for the supplier to honour ₹{po['total_amount']:,.0f} or cancel.")
    if po.get("vendor_email"):
        try:
            email_client.send_email(
                po["vendor_email"], make_subject(case_id, f"Purchase Order {po['po_number']} - revised price not accepted"),
                f"Dear {po['vendor_name']},\n\nWe are unable to accept a revised price for purchase order {po['po_number']}. "
                f"Please honour the agreed total of {po['total_amount']:,.2f} and confirm, or tell us if you cannot supply at that price.\n\nThank you.")
        except Exception:
            logger.exception("Price refusal email for %s failed", po["po_number"])
    operations_agent.publish_event(case_id, "po.price_change_rejected", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "asked_total": asked_total, "by": by, "note": note})


def mark_send_failed(case_id: str) -> None:
    """The order email bounced: it did not reach the supplier, so it is not "sent" any more. Retry once the address is fixed."""
    po = get_purchase_order(case_id)
    purchase_order_repository.update_status(po["purchase_order_id"], "send_failed")
    operations_agent.publish_event(case_id, "po.send_failed", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "total_amount": po["total_amount"], "status": "send_failed", "bounced": True})
