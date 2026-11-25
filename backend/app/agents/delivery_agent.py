import json
import logging
import uuid
from datetime import datetime, timezone

from app.agents import operations_agent
from app.clients import email_client
from app.core import agent_cases, goods_issues, partial_delivery, receipt
from app.core.email_parsing import make_subject
from app.core.exceptions import DeliveryAlreadyConfirmed, InvalidInput, PurchaseOrderNotFound
from app.repositories import goods_issue_repository, purchase_order_repository

logger = logging.getLogger(__name__)


def get_open_deliveries() -> list[dict]:
    """Sent purchase orders still awaiting delivery that have an expected date."""
    return [
        {
            "purchase_order_id": str(r.purchase_order_id),
            "po_number": f"PO-{r.po_number}",
            "case_id": str(r.case_id),
            "vendor_name": r.vendor_name,
            "vendor_email": r.vendor_email,
            "expected_delivery_date": r.expected_delivery_date,
            "chase_count": r.chase_count,
            "last_chased_at": r.last_chased_at,
            "escalated_at": r.escalated_at,
            # what is still owed, when part of the order has already arrived
            **_owed(r),
        }
        for r in purchase_order_repository.find_open_deliveries()
    ]


def _owed(row) -> dict:
    lines = _lines(row)
    received, ordered = partial_delivery.units(lines)
    return {"arrived": received, "ordered_units": ordered,
            "outstanding": partial_delivery.outstanding_text(lines) if partial_delivery.is_partial(lines) else ""}


def _lines(row) -> list[dict]:
    """Ordered / received / outstanding per item for a purchase order row."""
    return partial_delivery.progress(json.loads(row.items_json or "[]"), partial_delivery.parse_batches(getattr(row, "received_json", None)))


def chase_vendor(delivery: dict) -> bool:
    """Email the vendor about an overdue order. Returns False (and does not count a chase)
    if they could not be emailed, so the next tick tries again."""
    if not delivery["vendor_email"]:
        logger.warning("Cannot chase %s: vendor has no email", delivery["po_number"])
        return False

    po = delivery["po_number"]
    still = (f"We have received part of it ({delivery['arrived']} of {delivery['ordered_units']}). Still outstanding: {delivery['outstanding']}.\n\n"
             if delivery.get("outstanding") else "")
    body = (
        f"Dear {delivery['vendor_name']},\n\n"
        f"Our purchase order {po} was due for delivery on "
        f"{delivery['expected_delivery_date']:%d %b %Y} and we have not yet received "
        f"{'all of ' if still else ''}the goods.\n\n{still}"
        f"Please reply with the current delivery status and a firm delivery date.\n\nThank you."
    )
    try:
        email_client.send_email(
            delivery["vendor_email"], make_subject(delivery["case_id"], f"Delivery follow-up - {po}"), body,
        )
    except Exception:
        logger.exception("Delivery chase for %s failed", po)
        return False

    purchase_order_repository.mark_chased(delivery["purchase_order_id"])
    operations_agent.publish_event(
        delivery["case_id"], "delivery.chased", agent_name="Delivery Agent",
        payload={"po_number": po, "vendor": delivery["vendor_name"],
                 "chase_number": delivery["chase_count"] + 1},
    )
    return True


def mark_escalated(delivery: dict) -> None:
    purchase_order_repository.mark_escalated(delivery["purchase_order_id"])
    operations_agent.publish_event(
        delivery["case_id"], "delivery.escalated", agent_name="Delivery Agent",
        payload={"po_number": delivery["po_number"], "vendor": delivery["vendor_name"],
                 "expected_delivery_date": delivery["expected_delivery_date"].isoformat()},
    )


def confirm_received(case_id: str, received_by: str, note: str | None, items: dict[str, int] | None = None) -> dict:
    """Record goods that arrived. `items` is {item name: quantity}; leave it out to receive everything still owed.
    The order is "delivered" once every item is in; until then it stays open and the supplier is chased for the rest."""
    row = purchase_order_repository.find_purchase_order_by_case_id(case_id)
    if row is None:
        raise PurchaseOrderNotFound(case_id)
    if row.delivery_status == "delivered":
        raise DeliveryAlreadyConfirmed(case_id)

    po_items = json.loads(row.items_json or "[]")
    old_json = getattr(row, "received_json", None)
    batches = partial_delivery.parse_batches(old_json)
    try:
        added = partial_delivery.normalise_receipt(po_items, batches, items)
    except partial_delivery.BadReceipt as exc:
        raise InvalidInput(str(exc)) from exc

    batch = {"at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), "by": received_by, "note": note, "items": added}
    if not purchase_order_repository.append_receipt(str(row.purchase_order_id), old_json, json.dumps(batches + [batch])):
        raise InvalidInput("Someone else has just recorded a delivery on this order. Refresh the page and check what has arrived.")

    lines = partial_delivery.progress(po_items, batches + [batch])
    received, ordered = partial_delivery.units(lines)
    po_number = f"PO-{row.po_number}"
    if partial_delivery.is_complete(lines):
        if not purchase_order_repository.mark_delivered(str(row.purchase_order_id), received_by, note):
            raise DeliveryAlreadyConfirmed(case_id)
        operations_agent.publish_event(
            case_id, "delivery.received", agent_name="Delivery Agent",
            payload={"po_number": po_number, "received_by": received_by, "note": note,
                     **({"in_parts": len(batches) + 1} if batches else {})},
        )
    else:
        operations_agent.publish_event(
            case_id, "delivery.partial", agent_name="Delivery Agent",
            payload={"po_number": po_number, "received_by": received_by, "note": note, "items": added,
                     "received_units": received, "ordered_units": ordered, "outstanding": partial_delivery.outstanding_text(lines)},
        )
    return {**get_delivery(case_id), "just_received": added}


def over_delivery(case_id: str, items: dict[str, int] | None) -> list[dict]:
    """Lines of a receipt that are MORE than is still owed on the order (empty for "receive everything still owed")."""
    row = purchase_order_repository.find_purchase_order_by_case_id(case_id)
    if row is None or not items:
        return []
    po_items = json.loads(row.items_json or "[]")
    lines = partial_delivery.progress(po_items, partial_delivery.parse_batches(getattr(row, "received_json", None)))
    return agent_cases.over_delivery(po_items, {l["description"]: l["outstanding"] for l in lines}, items)


def short_close(case_id: str, closed_by: str, note: str | None) -> dict:
    """The supplier will not send the rest and a person accepts that: the order counts as delivered as it stands."""
    row = purchase_order_repository.find_purchase_order_by_case_id(case_id)
    if row is None:
        raise PurchaseOrderNotFound(case_id)
    if row.delivery_status == "delivered":
        raise DeliveryAlreadyConfirmed(case_id)
    lines = _lines(row)
    if not partial_delivery.is_partial(lines):
        raise InvalidInput("Nothing has arrived yet, so there is no part delivery to close. Record what arrived first.")
    if not purchase_order_repository.mark_short_closed(str(row.purchase_order_id), closed_by, note):
        raise DeliveryAlreadyConfirmed(case_id)
    operations_agent.publish_event(
        case_id, "delivery.short_closed", agent_name="Delivery Agent",
        payload={"po_number": f"PO-{row.po_number}", "by": closed_by, "note": note, "missing": partial_delivery.outstanding_text(lines),
                 "received_units": partial_delivery.units(lines)[0], "ordered_units": partial_delivery.units(lines)[1]},
    )
    return get_delivery(case_id)


def get_delivery(case_id: str) -> dict:
    row = purchase_order_repository.find_purchase_order_by_case_id(case_id)
    if row is None:
        raise PurchaseOrderNotFound(case_id)
    return {
        "case_id": str(row.case_id),
        "po_number": f"PO-{row.po_number}",
        "vendor_name": row.vendor_name,
        "expected_delivery_date": row.expected_delivery_date,
        "delivery_status": row.delivery_status,
        "delivered_at": row.delivered_at,
        "received_by": row.received_by,
        "delivery_note": row.delivery_note,
        "chase_count": row.chase_count,
        "last_chased_at": row.last_chased_at,
        "escalated_at": row.escalated_at,
        "items": (lines := _lines(row)),
        "batches": partial_delivery.parse_batches(getattr(row, "received_json", None)),
        "received_units": partial_delivery.units(lines)[0],
        "ordered_units": partial_delivery.units(lines)[1],
        "partial": partial_delivery.is_partial(lines),
        "short_closed_at": getattr(row, "short_closed_at", None),
    }


def get_receipt(case_id: str) -> dict:
    """The requester's answer to "did the goods reach you?" (see core/receipt.py)."""
    try:
        delivered = get_delivery(case_id)["delivery_status"] == "delivered"
    except PurchaseOrderNotFound:
        delivered = False
    return receipt.receipt_state(delivered, operations_agent.get_case_events(case_id))


def record_receipt(case_id: str, requester: str, received: bool, note: str | None) -> None:
    operations_agent.publish_event(
        case_id, receipt.CONFIRMED if received else receipt.DISPUTED, agent_name="Delivery Agent",
        payload={"by": requester, "note": receipt.clean_note(note)},
    )


def record_dispute_handled(case_id: str, handled_by: str, note: str | None) -> None:
    operations_agent.publish_event(
        case_id, receipt.HANDLED, agent_name="Delivery Agent",
        payload={"by": handled_by, "note": receipt.clean_note(note)},
    )


def get_open_disputes() -> dict[str, dict]:
    """Cases where the requester said the goods did not arrive and nobody has followed up yet."""
    return receipt.open_disputes(operations_agent.get_events_of_types(receipt.RECEIPT_EVENTS))


# ---------------------------------------------------------------------------------------------
# Wrong or damaged goods (core/goods_issues.py)

def _issue_dict(r) -> dict:
    return {
        "issue_id": str(r.issue_id), "case_id": str(r.case_id), "purchase_order_id": str(r.purchase_order_id), "po_number": f"PO-{r.po_number}",
        "vendor_name": r.vendor_name, "vendor_email": r.vendor_email, "kind": r.kind, "items": json.loads(r.items_json or "[]"),
        "description": r.description, "reported_by": r.reported_by, "reported_at": r.reported_at, "status": r.status,
        "supplier_told_at": r.supplier_told_at, "supplier_replied_at": r.supplier_replied_at, "chase_count": r.chase_count or 0,
        "last_chased_at": r.last_chased_at, "escalated_at": r.escalated_at, "resolution": r.resolution,
        "credit_amount": float(r.credit_amount) if r.credit_amount is not None else None, "resolution_note": r.resolution_note,
        "resolved_by": r.resolved_by, "resolved_at": r.resolved_at,
        "return_status": getattr(r, "return_status", None), "return_ref": getattr(r, "return_ref", None), "returned_at": getattr(r, "returned_at", None),
        "returned_by": getattr(r, "returned_by", None), "replacement_status": getattr(r, "replacement_status", None),
        "replacement_expected_at": getattr(r, "replacement_expected_at", None), "replacement_received_at": getattr(r, "replacement_received_at", None),
        "credit_note_number": getattr(r, "credit_note_number", None),
    }


def get_issues(case_id: str) -> list[dict]:
    return [_issue_dict(r) for r in goods_issue_repository.find_by_case(case_id)]


def get_open_issues() -> list[dict]:
    """Every open goods problem on an open case (for the worker and My work)."""
    return [_issue_dict(r) for r in goods_issue_repository.find_open()]


def get_issue(issue_id: str) -> dict:
    row = goods_issue_repository.find_by_id(issue_id)
    if row is None:
        raise InvalidInput("That goods problem was not found.")
    return _issue_dict(row)


def report_issue(case_id: str, kind: str, items: dict[str, int] | None, description: str | None, by: str) -> dict:
    """Record a problem with goods that arrived, and ask the supplier to put it right."""
    row = purchase_order_repository.find_purchase_order_by_case_id(case_id)
    if row is None:
        raise PurchaseOrderNotFound(case_id)
    po_items = json.loads(row.items_json or "[]")
    if row.delivery_status == "delivered" and not getattr(row, "received_json", None):
        arrived = {" ".join(i["description"].lower().split()): i["quantity"] for i in po_items}     # delivered before parts were tracked
    else:
        arrived = partial_delivery.received_totals(partial_delivery.parse_batches(getattr(row, "received_json", None)))
    try:
        affected, text = goods_issues.validate_report(po_items, arrived, kind, items, description)
    except goods_issues.BadIssue as exc:
        raise InvalidInput(str(exc)) from exc

    issue_id = str(uuid.uuid4())
    goods_issue_repository.insert_issue(issue_id, case_id, str(row.purchase_order_id), kind, affected, text, by)
    po_number = f"PO-{row.po_number}"
    sent = False
    if row.vendor_email:
        try:
            email_client.send_email(row.vendor_email, make_subject(case_id, f"Purchase Order {po_number} - goods problem"),
                                    goods_issues.supplier_message(row.vendor_name, po_number, kind, affected, text))
            goods_issue_repository.mark_supplier_told(issue_id)
            sent = True
        except Exception:
            logger.exception("Goods problem email for %s to %s failed", po_number, row.vendor_name)
    operations_agent.publish_event(
        case_id, "goods.issue_reported", agent_name="Delivery Agent",
        payload={"issue_id": issue_id, "po_number": po_number, "vendor": row.vendor_name, "kind": kind, "items": affected,
                 "description": text, "by": by, "supplier_told": sent},
    )
    return get_issue(issue_id)


def resolve_issue(issue_id: str, resolution: str, credit_amount, note: str | None, by: str, credit_note_number: str | None = None) -> dict:
    issue = get_issue(issue_id)
    row = purchase_order_repository.find_purchase_order_by_case_id(issue["case_id"])
    try:
        credit = goods_issues.validate_resolution(resolution, credit_amount, float(row.total_amount) if row and row.total_amount is not None else None)
    except goods_issues.BadIssue as exc:
        raise InvalidInput(str(exc)) from exc
    clean = (note or "").strip()[:500] or None
    try:
        number = goods_issues.clean_ref(credit_note_number) if resolution == "credit" else None
    except goods_issues.BadIssue as exc:
        raise InvalidInput(str(exc)) from exc
    if not goods_issue_repository.resolve(issue_id, resolution, credit, clean, by, number):
        raise InvalidInput("This problem has already been closed.")
    operations_agent.publish_event(
        issue["case_id"], "goods.issue_resolved", agent_name="Delivery Agent",
        payload={"issue_id": issue_id, "po_number": issue["po_number"], "resolution": resolution, "credit_amount": credit, "by": by, "note": clean,
                 **({"credit_note_number": number} if number else {})},
    )
    return get_issue(issue_id)


def return_goods(issue_id: str, by: str, ref: str | None) -> dict:
    """The faulty goods are going back to the supplier: recorded, the supplier is told what is coming (once), and the case says so."""
    issue = get_issue(issue_id)
    try:
        goods_issues.check_can_return(issue)
        ref = goods_issues.clean_ref(ref)
    except goods_issues.BadIssue as exc:
        raise InvalidInput(str(exc)) from exc
    if not goods_issue_repository.mark_returned(issue_id, by, ref):
        raise InvalidInput("The goods have already been marked as returned.")
    told = False
    if issue.get("vendor_email"):
        try:
            email_client.send_email(issue["vendor_email"], make_subject(issue["case_id"], f"Purchase Order {issue['po_number']} - goods being returned"),
                                    goods_issues.return_notice(issue["vendor_name"], issue["po_number"], issue["items"], ref))
            told = True
        except Exception:
            logger.exception("Return notice for %s to %s failed", issue["po_number"], issue["vendor_name"])
    operations_agent.publish_event(issue["case_id"], "goods.returned", agent_name="Delivery Agent",
                                   payload={"issue_id": issue_id, "po_number": issue["po_number"], "items": issue["items"], "ref": ref, "by": by, "supplier_told": told})
    return get_issue(issue_id)


def expect_replacement(issue_id: str, by: str) -> dict:
    """The supplier promised to send replacements: the problem stays open (payment stays held) until they arrive; reminders stop."""
    issue = get_issue(issue_id)
    try:
        goods_issues.check_can_expect_replacement(issue)
    except goods_issues.BadIssue as exc:
        raise InvalidInput(str(exc)) from exc
    if not goods_issue_repository.mark_replacement_expected(issue_id):
        raise InvalidInput("A replacement is already expected for this problem.")
    operations_agent.publish_event(issue["case_id"], "goods.replacement_expected", agent_name="Delivery Agent",
                                   payload={"issue_id": issue_id, "po_number": issue["po_number"], "items": issue["items"], "by": by})
    return get_issue(issue_id)


def receive_replacement(issue_id: str, by: str, note: str | None) -> dict:
    """The replacement arrived: recorded, and the problem ends as 'replaced' (the caller then puts stock back and releases the invoice)."""
    issue = get_issue(issue_id)
    try:
        goods_issues.check_can_receive_replacement(issue)
    except goods_issues.BadIssue as exc:
        raise InvalidInput(str(exc)) from exc
    if not goods_issue_repository.mark_replacement_received(issue_id):
        raise InvalidInput("The replacement has already been recorded.")
    operations_agent.publish_event(issue["case_id"], "goods.replacement_received", agent_name="Delivery Agent",
                                   payload={"issue_id": issue_id, "po_number": issue["po_number"], "items": issue["items"], "by": by})
    return resolve_issue(issue_id, "replaced", None, note or "The replacement arrived.", by)


def note_supplier_reply(case_id: str, snippet: str, sender: str) -> bool:
    """The supplier wrote back while a goods problem is open: record it and stop chasing them. False if nothing was open."""
    open_ones = goods_issues.open_issues(get_issues(case_id))
    if not open_ones:
        return False
    goods_issue_repository.mark_supplier_replied(case_id)
    operations_agent.publish_event(case_id, "goods.supplier_replied", agent_name="Delivery Agent",
                                   payload={"issue_ids": [i["issue_id"] for i in open_ones], "from": sender, "snippet": snippet[:300]})
    return True


def chase_issue(issue: dict) -> bool:
    if not issue.get("vendor_email"):
        return False
    body = (f"Dear {issue['vendor_name']},\n\nWe have not yet heard how you will put right the problem with purchase order {issue['po_number']} "
            f"({goods_issues.affected_text(issue['items'])}). Please reply to say whether you will replace the items or issue a credit note.\n\nThank you.")
    try:
        email_client.send_email(issue["vendor_email"], make_subject(issue["case_id"], f"Purchase Order {issue['po_number']} - goods problem reminder"), body)
    except Exception:
        logger.exception("Goods problem reminder for %s failed", issue["po_number"])
        return False
    goods_issue_repository.mark_chased(issue["issue_id"])
    operations_agent.publish_event(issue["case_id"], "goods.issue_chased", agent_name="Delivery Agent",
                                   payload={"issue_id": issue["issue_id"], "number": issue["chase_count"] + 1})
    return True


def mark_issue_overdue(issue: dict) -> None:
    goods_issue_repository.mark_escalated(issue["issue_id"])
    operations_agent.publish_event(issue["case_id"], "goods.issue_overdue", agent_name="Delivery Agent",
                                   payload={"issue_id": issue["issue_id"], "po_number": issue["po_number"], "vendor": issue["vendor_name"],
                                            "reminders": issue["chase_count"]})
