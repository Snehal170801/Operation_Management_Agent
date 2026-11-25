"""
Owns the sequence of the procure-to-pay flow: which agent runs after which,
and where the case branches (e.g. stock sufficient -> close case early;
approval rejected -> close case). Agents never call each other directly --
they only get called from here. This is what stays readable as agents are
added, instead of every agent secretly knowing about every other agent.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import logging
import re

from app.agents import (
    approval_agent,
    delivery_agent,
    invoice_agent,
    notification_agent,
    operations_agent,
    procurement_agent,
    purchase_agent,
    purchase_order_agent,
    vendor_agent,
)
from app.agents import approval_link_agent, calling_agent, document_agent
from app.core import agent_cases, attachments, automation, file_hash, negotiation, restock, tax, bounce, change_policy, combine, goods_issues, price_change, resource_policy, stuck_policy, supplier_documents, urgency
from app.core import quote_expiry
from app.core import quotes as quote_rules
from app.core.config import settings
from app.core.escalation import due_escalations
from app.core.email_parsing import REF_PREFIX, clean_reply_body, parse_case_ref
from app.core.exceptions import CaseNotFound, DocumentAlreadyHandled, InvalidInput, PurchaseRequestNotFound, QuoteExpired, VendorNotApproved
from app.core.delivery_policy import next_delivery_action
from app.core.exceptions import NotAnInvoice
from app.core.invoice_chase_policy import next_invoice_chase_action
from app.core.po_confirm_policy import next_confirm_action
from app.core.invoice_policy import evaluate_invoice
from app.core.sourcing_policy import next_sourcing_action

logger = logging.getLogger(__name__)


def start_case(requester_id: str, raw_request: str, needed_by=None, urgent: bool = False) -> str:
    case_id = operations_agent.create_case(requester_id=requester_id)
    with operations_agent.working(case_id, "read_request"):
        purchase_agent.create_purchase_request(case_id=case_id, raw_request=raw_request, needed_by=needed_by, urgent=urgent)
    with operations_agent.working(case_id, "check_stock"):
        stock_result = procurement_agent.check_stock(case_id=case_id)
    if not stock_result["sufficient"]:
        _source_or_hold(case_id)
    return case_id


def _source_or_hold(case_id: str) -> None:
    """Stock can't cover it: ask vendors for quotes (from here the background worker takes over: reminders, ranking, approval),
    or, with automation paused, leave the case at 'sourcing_needed' for the worker to pick up once it is resumed."""
    if automation.is_paused():
        operations_agent.publish_event(
            case_id, "automation.held", agent_name="Operations Agent",
            payload={"waiting_for": "quote requests"},
        )
    else:
        _request_quotes(case_id)


def restock_item(item: str, quantity: int, requested_by: str, needed_by=None, urgent: bool = False) -> str:
    """Order more of an item that is running low. Same road as any request (quotes, ranking, approval, order, delivery, invoice),
    except it never looks in stock: the point is that stock is short, and what is on the shelf must not fill it."""
    case_id = operations_agent.create_case(requester_id=requested_by)
    with operations_agent.working(case_id, "read_request"):
        purchase_agent.create_restock_request(case_id, item, quantity, requested_by, needed_by=needed_by, urgent=urgent)
    operations_agent.publish_event(
        case_id, "restock.requested", agent_name="Purchase Agent",
        payload={"item": item, "quantity": quantity, "by": requested_by},
    )
    operations_agent.set_stage(case_id, "sourcing_needed")
    _source_or_hold(case_id)
    return case_id


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


AUTO_REORDER_ACTOR = "Procurement Agent"


def _open_reorder_items() -> set[str]:
    """Lower-case names of the items that have a reorder in progress (manual or automatic). A case that cannot be read does not count."""
    def is_open(case_id: str) -> bool:
        try:
            return operations_agent.get_case_status(case_id)["status"] == "open" and restock.on_the_way(operations_agent.get_case_events(case_id))
        except Exception:
            return False
    return set(restock.open_orders(operations_agent.get_events_of_types(("restock.requested",)), is_open))


def auto_reorder_low_stock() -> int:
    """When an item has reached its minimum, raise a reorder by itself (the existing restock road: quotes, ranking, and an approver ALWAYS
    approves a reorder). Off unless AUTO_REORDER_ENABLED. Never twice for an item while one is in progress, a cool-down after each, and a cap
    per pass so a first run over many low items cannot flood anyone. A failure for one item never stops the others. Returns how many were raised."""
    if not settings.AUTO_REORDER_ENABLED:
        return 0
    now = _now()
    last_auto: dict[str, datetime] = {}
    for e in operations_agent.get_events_of_types(("restock.auto_triggered",)):
        item = ((e.get("payload") or {}).get("item") or "").strip().lower()
        if item:
            last_auto[item] = max(e["created_at"], last_auto.get(item, e["created_at"]))
    candidates = restock.auto_candidates(procurement_agent.get_all_stock(), _open_reorder_items(), last_auto, now,
                                         settings.AUTO_REORDER_COOLDOWN_HOURS, settings.AUTO_REORDER_MAX_PER_PASS)
    raised = 0
    for c in candidates:
        try:
            case_id = restock_item(c["item"], c["quantity"], AUTO_REORDER_ACTOR)
            operations_agent.publish_event(case_id, "restock.auto_triggered", agent_name="Procurement Agent",
                                           payload={"item": c["item"], "quantity": c["quantity"], "on_hand": c["on_hand"], "min_level": c["min_level"]})
            raised += 1
        except Exception:
            logger.exception("Automatic reorder of %s failed", c["item"])
            continue
        try:
            notification_agent.notify_case_stalled(
                case_id, f"{c['item']} is down to {c['on_hand']} (its minimum is {c['min_level']}), so a reorder of {c['quantity']} was started automatically. "
                         f"An approver must approve it before anything is ordered.", team="procurement")
        except Exception:
            logger.exception("Could not tell Stores about the automatic reorder of %s", c["item"])
    return raised


def _terms(request: dict) -> dict:
    """How hard to chase for this request: how long suppliers get to quote, and the line that tells them it is urgent."""
    urgent, needed_by = bool(request.get("urgent")), request.get("needed_by")
    return {
        "deadline_hours": urgency.quote_deadline_hours(urgent, needed_by, _now(), settings.RFQ_DEADLINE_HOURS, settings.URGENT_RFQ_DEADLINE_HOURS),
        "note": urgency.request_note(urgent, needed_by),
        "preferred_vendor_ids": _preferred_for(request),
    }


def _preferred_for(request: dict) -> list[str]:
    """The suppliers marked as preferred for the items on this request. Never lets a problem here stop quotes going out."""
    try:
        return procurement_agent.preferred_vendor_ids(request.get("items", []))
    except Exception:
        logger.exception("Could not look up the preferred suppliers")
        return []


def _request_quotes(case_id: str) -> None:
    """Email the suppliers for prices; if nobody could be reached, tell a person."""
    request = purchase_agent.get_purchase_request(case_id)
    items = request["items"]
    with operations_agent.working(case_id, "request_quotes"):
        invited = vendor_agent.send_rfqs(case_id, items, **_terms(request))
    # Then ring them (if switched on) to say "please check your email". Never affects the case if it fails.
    calling_agent.notify_email_sent(case_id, invited, "rfq")
    if not invited:
        notification_agent.notify_case_stalled(
            case_id, "No vendor could be emailed (none has an email address, or sending failed).", team="vendor",
        )
    else:
        try:
            suggest_combines(case_id)
        except Exception:
            logger.exception("Looking for requests to combine failed for case %s", case_id)      # a nicety: it must never hold up the request


def ingest_quote_email(message: dict) -> str:
    """Turn a vendor's emailed reply into a quote. `message` has from_email, subject, body.
    Returns what happened: quoted | no_case | not_invited | not_accepting | empty | own_message."""
    if message.get("outbound"):
        return "own_message"  # something we sent ourselves, not a supplier's reply

    if bounce.is_bounce(message):
        return handle_bounce(message)

    if supplier_documents.is_auto_reply(message.get("subject"), message.get("body")):
        return _ignore_auto_reply(message)

    case_id = parse_case_ref(message["subject"]) or _case_from_po_number(message)
    if case_id is None:
        return _keep_unmatched_document(message)

    try:
        case = operations_agent.get_case_status(case_id)
    except CaseNotFound:
        return "no_case"

    vendor_id = vendor_agent.find_invited_vendor_id(case_id, message["from_email"])
    if vendor_id is None:
        operations_agent.publish_event(
            case_id, "quote.email_ignored", agent_name="Vendor Agent",
            payload={"from": message["from_email"], "reason": "Sender is not an invited vendor."},
        )
        return "not_invited"

    fresh, repeated, to_remember = file_hash.split(message.get("attachments") or [], document_agent.known_file_hashes(case_id))
    if repeated:
        operations_agent.publish_event(case_id, "document.duplicate_file", agent_name="Vendor Agent",
                                       payload={"from": message["from_email"], "files": [a["name"] for a in repeated], "read_again": bool(fresh)})
        message = {**message, "attachments": fresh}
        if not fresh and not clean_reply_body(message.get("body") or ""):
            return "duplicate_file"              # the same file again and nothing new written: it was read the first time

    written = clean_reply_body(message.get("body") or "")
    if written and case["stage"] not in _PO_STAGES:          # (after the order, a repeated invoice mail is judged by the invoice rules instead: duplicate number -> Accounts)
        words = file_hash.fingerprint({"text": f"{message['from_email'].lower()}|{written}"})
        if words in document_agent.known_file_hashes(case_id) and not fresh:
            operations_agent.publish_event(case_id, "email.duplicate", agent_name="Vendor Agent",
                                           payload={"from": message["from_email"], "snippet": written[:200]})
            return "duplicate_email"             # word for word what this supplier already sent on this case: noted, not handled twice
        to_remember = [*to_remember, (words, "(email text)")]

    _note_unsupported_files(case_id, vendor_id, message)
    outcome = _route_vendor_mail(case_id, case, vendor_id, message)
    if outcome not in ("empty", "not_accepting"):
        document_agent.remember_files(case_id, to_remember)         # only once it was handled, so a crash lets the mail be read again
    return outcome


def _route_vendor_mail(case_id: str, case: dict, vendor_id: str, message: dict) -> str:
    """What to do with a mail from an invited supplier, by where the case is: a reply about the order, a revised price, or a quote."""
    if case["stage"] in _PO_STAGES:
        return _ingest_po_reply(case_id, vendor_id, message)

    if case["stage"] == "awaiting_approval":
        return _revise_quote(case_id, vendor_id, message)

    if case["stage"] == negotiation.STAGE:
        return _ingest_negotiation_reply(case_id, vendor_id, message)

    if case["stage"] != "awaiting_quotes":
        operations_agent.publish_event(
            case_id, "quote.email_ignored", agent_name="Vendor Agent",
            payload={"from": message["from_email"],
                     "reason": f"Case is no longer collecting quotes (stage: {case['stage']})."},
        )
        return "not_accepting"

    text = _reply_text(message)
    pictures = _page_pictures(message)             # a scan is read even when the supplier wrote a cover note ("quote attached")
    if not text and not pictures:
        operations_agent.publish_event(
            case_id, "quote.email_ignored", agent_name="Vendor Agent",
            payload={"from": message["from_email"], "reason": _unreadable_reason(message)},
        )
        _flag_unreadable_document(case_id, message, vendor_id, team="vendor")
        return "empty"
    if _points_at_unread_file(message, pictures, text):
        _flag_unreadable_document(case_id, message, vendor_id, team="vendor")
        return "empty"

    if text and not pictures and supplier_documents.is_decline(text):
        return _react_to_decline(case_id, vendor_id, message, text)
    if text and not pictures and supplier_documents.is_question(text):
        return _react_to_question(case_id, vendor_id, message, text)
    if text and not pictures and supplier_documents.is_no_price(text):
        return _react_to_no_price(case_id, vendor_id, message, text)

    with _reading(case_id, message, team="vendor"), operations_agent.working(case_id, "read_quote"):
        if pictures:
            vendor_agent.submit_quote(case_id, vendor_id, text or "(scanned document: read from the page pictures)", images=pictures)
        else:
            vendor_agent.submit_quote(case_id, vendor_id, text)
    _flag_partial_quote(case_id, vendor_id, text)
    advance_sourcing(case_id)  # react now (e.g. everyone replied) instead of next tick
    return "quoted"


def _react_to_question(case_id: str, vendor_id: str, message: dict, text: str) -> str:
    """A supplier asks us something instead of quoting. The Vendor team is told with their words, the case says so (the supplier is NOT
    chased for a price while they wait on us), and the request keeps waiting visibly: it is not counted as an answer."""
    name = _vendor_name(vendor_id, message["from_email"])
    operations_agent.publish_event(case_id, "quote.question", agent_name="Vendor Agent",
                                   payload={"vendor_id": vendor_id, "vendor": name, "from": message["from_email"], "snippet": text[:400]})
    notification_agent.notify_case_stalled(
        case_id, f"{name} has a question before they can quote: \"{text[:300]}\". Please answer them (reply to their email); the request is waiting for their price.",
        team="vendor")
    return "question"


def _flag_partial_quote(case_id: str, vendor_id: str, text: str) -> None:
    """A quote that names some of the requested items but skips others is flagged for the Vendor team (it still counts; a person decides
    whether to ask for the rest). Never raises: a failure here must not lose the quote."""
    try:
        wanted = [i["description"] for i in purchase_agent.get_purchase_request(case_id)["items"]]
        missing = supplier_documents.items_missing_from_quote(wanted, text)
        if not missing:
            return
        name = _vendor_name(vendor_id, "A supplier")
        operations_agent.publish_event(case_id, "quote.partial", agent_name="Vendor Agent", payload={"vendor_id": vendor_id, "vendor": name, "missing": missing})
        notification_agent.notify_case_stalled(
            case_id, f"{name}'s quote does not mention: {', '.join(missing)}. It may cover only some of the request. Please check before approving.", team="vendor")
    except Exception:
        logger.exception("Could not check whether the quote on case %s covers every item", case_id)


def _note_unsupported_files(case_id: str, vendor_id: str, message: dict) -> None:
    """A file of a kind we never read (zip, Word, old Excel...) came with a mail that otherwise reads fine: the case says a file was skipped,
    the supplier is asked (at most twice per case) for a PDF or Excel, and the Vendor team is told. A mail with NOTHING readable is handled by
    the unreadable-document rule, so it is not announced twice."""
    skipped = supplier_documents.unsupported_files(message.get("attachments") or [])
    if not skipped or not _reply_text(message):
        return
    try:
        name = _vendor_name(vendor_id, message["from_email"])
        operations_agent.publish_event(case_id, "document.unsupported_file", agent_name="Vendor Agent", payload={"from": message["from_email"], "files": skipped})
        notification_agent.notify_case_stalled(case_id, f"{name} attached a file we cannot read ({', '.join(skipped)}); the rest of their email was read. "
                                                        f"Please open the email if the file matters.", team="vendor")
        asked = sum(1 for e in operations_agent.get_case_events(case_id) if e["event_type"] == "document.resend_requested")
        if asked < _MAX_RESEND_ASKS:
            invoice_agent.ask_to_resend(case_id, message["from_email"], name)
    except Exception:
        logger.exception("Could not note the unsupported file on case %s", case_id)


def _ignore_auto_reply(message: dict) -> str:
    """An out-of-office reply: nothing is answered, read as a quote or counted as the supplier replying (and so it can never loop). When it
    names a case the case timeline notes it, so the silence is explained, not hidden."""
    case_id = parse_case_ref(message.get("subject") or "")
    if case_id:
        try:
            operations_agent.get_case_status(case_id)
            operations_agent.publish_event(case_id, "email.auto_reply", agent_name="Vendor Agent",
                                           payload={"from": message.get("from_email"), "subject": (message.get("subject") or "")[:120]})
        except CaseNotFound:
            pass
    return "auto_reply"


def _vendor_name(vendor_id: str, fallback: str) -> str:
    return next((v["name"] for v in vendor_agent.get_all_vendors() if v["vendor_id"].lower() == vendor_id.lower()), fallback)


def _react_to_decline(case_id: str, vendor_id: str, message: dict, text: str) -> str:
    """A supplier says they cannot supply. That is an answer: no quote is made, we stop waiting on them, the Vendor team is told, and if
    everyone has now answered without a price the request goes to a person straight away (not at the deadline)."""
    name = _vendor_name(vendor_id, message["from_email"])
    vendor_agent.mark_declined(case_id, vendor_id)
    operations_agent.publish_event(case_id, "quote.declined", agent_name="Vendor Agent",
                                   payload={"vendor_id": vendor_id, "vendor": name, "from": message["from_email"], "snippet": text[:300]})
    notification_agent.notify_case_stalled(case_id, f"{name} says they cannot supply this request: \"{text[:200]}\". We are no longer waiting for them.", team="vendor")
    advance_sourcing(case_id)
    return "declined"


def _react_to_no_price(case_id: str, vendor_id: str, message: dict, text: str) -> str:
    """A supplier replied without any price (a question, 'we will revert'). Not a quote: they are still waited on and reminded, the
    Vendor team is told with what they wrote, and they are asked for a price once (a second such reply only logs, so it cannot loop)."""
    name = _vendor_name(vendor_id, message["from_email"])
    again = any(e["event_type"] == "quote.no_price" and e["payload"].get("vendor_id") == vendor_id for e in operations_agent.get_case_events(case_id))
    asked = False if again else vendor_agent.ask_for_price(case_id, vendor_id)
    operations_agent.publish_event(case_id, "quote.no_price", agent_name="Vendor Agent",
                                   payload={"vendor_id": vendor_id, "vendor": name, "from": message["from_email"], "snippet": text[:300], "asked": asked, "repeat": again})
    if not again:
        notification_agent.notify_case_stalled(
            case_id, f"{name} replied without a price: \"{text[:200]}\". "
                     f"{'We asked them for a price.' if asked else 'They could not be asked by email, so please contact them.'}", team="vendor")
    return "no_price"


def handle_bounce(message: dict) -> str:
    """The mail server says an email of ours did not arrive. A permanent failure to a supplier's address means we stop
    waiting on them, the Vendor team is told, and the address is flagged until someone fixes it."""
    info = bounce.parse(message)
    if not info["address"] or not info["permanent"]:
        return "bounce_ignored"                         # a full mailbox or a hiccup: the supplier may still answer
    vendor = vendor_agent.find_vendor_by_email(info["address"])
    if vendor is None:
        return "bounce_unknown_address"                 # not a supplier of ours (a requester, say): nothing to do here
    vendor_agent.mark_email_bounced(vendor["vendor_id"], info["reason"])

    case_ids: list[str] = []
    if info["case_id"]:
        try:
            if operations_agent.get_case_status(info["case_id"])["status"] == "open":
                case_ids = [info["case_id"]]
        except CaseNotFound:
            pass
    if not case_ids:
        case_ids = vendor_agent.open_case_ids_for_vendor(vendor["vendor_id"])
    for case_id in case_ids:
        _tell_about_bounce(case_id, vendor, info)
    return "bounced"


def _tell_about_bounce(case_id: str, vendor: dict, info: dict) -> None:
    case = operations_agent.get_case_status(case_id)
    po = purchase_order_agent.find_purchase_order(case_id)
    is_order = info["about"] == "order" or (info["about"] is None and po is not None and po["vendor_id"] == vendor["vendor_id"] and po["status"] == "sent")
    operations_agent.publish_event(case_id, "email.bounced", agent_name="Notification Agent",
                                   payload={"vendor": vendor["name"], "address": info["address"], "reason": info["reason"], "about": "order" if is_order else "quote"})
    if is_order:
        if po and po["vendor_id"] == vendor["vendor_id"] and po["status"] == "sent" and delivery_agent.get_delivery(case_id)["delivery_status"] == "pending":
            purchase_order_agent.mark_send_failed(case_id)
            operations_agent.set_stage(case_id, "po_send_failed")
        notification_agent.notify_case_stalled(
            case_id, f"The order email to {vendor['name']} bounced ({info['reason']}). The address {info['address']} does not work. "
                     f"Fix it on the Vendors page, then retry sending the order.", team="po")
        return
    vendor_agent.mark_rfq_bounced(case_id, vendor["vendor_id"])
    notification_agent.notify_case_stalled(
        case_id, f"The quote request to {vendor['name']} bounced ({info['reason']}). The address {info['address']} does not work, so we are no longer "
                 f"waiting for them. Fix it on the Vendors page.", team="vendor")
    if case["stage"] == "awaiting_quotes":
        advance_sourcing(case_id)                       # maybe everyone else has replied already


def _revise_quote(case_id: str, vendor_id: str, message: dict) -> str:
    """A supplier sends a (new or revised) price while the order waits for an approver. It replaces their earlier price and
    the choice is made again, so the approver never decides on a price the supplier has already withdrawn."""
    text = _reply_text(message)
    pictures = _page_pictures(message)
    if not text and not pictures:
        operations_agent.publish_event(case_id, "quote.email_ignored", agent_name="Vendor Agent",
                                       payload={"from": message["from_email"], "reason": _unreadable_reason(message)})
        return "empty"
    before = {q["vendor_id"]: q for q in quote_rules.latest_per_vendor(vendor_agent.get_quotes(case_id))}.get(vendor_id)
    with _reading(case_id, message, team="vendor"), operations_agent.working(case_id, "read_quote"):
        if pictures:
            quote = vendor_agent.submit_quote(case_id, vendor_id, text or "(scanned document: read from the page pictures)", images=pictures)
        else:
            quote = vendor_agent.submit_quote(case_id, vendor_id, text)
    operations_agent.publish_event(
        case_id, "quote.revised", agent_name="Vendor Agent",
        payload={"vendor_id": vendor_id, "old_price": before["price"] if before else None, "new_price": quote["price"]})
    rank_and_review(case_id)
    return "quote_revised"


def _reply_text(message: dict) -> str:
    """What the supplier wrote, plus the readable text of any PDF / Excel / CSV they attached
    (quotes and invoices very often arrive as a file rather than in the email body)."""
    written = clean_reply_body(message["body"])
    files = attachments.combine(message.get("attachments", []))
    return "\n\n".join(part for part in (written, files) if part)


def supplier_addresses() -> tuple[str, ...]:
    """The email addresses of our suppliers: mail from them is read even when it carries no case tag. Never raises."""
    try:
        return tuple(v["email"] for v in vendor_agent.get_all_vendors() if v.get("email"))
    except Exception:
        logger.exception("Could not list the supplier addresses for the mailbox reader")
        return ()


def _keep_unmatched_document(message: dict) -> str:
    """A known supplier sent something that looks like a document, but it names no order we can find: keep it for a person to attach
    to the right case, and tell Accounts. Anything else with no case (mail from a stranger, chit-chat) is not ours: "no_case"."""
    try:
        vendor = vendor_agent.find_vendor_by_email(message.get("from_email") or "")
        if vendor is None or not document_agent.looks_like_a_document(message):
            return "no_case"
        document_agent.record(message, vendor["name"])
        notification_agent.notify_unmatched_document(
            message["from_email"], vendor["name"], message.get("subject") or "", [a["name"] for a in message.get("attachments", [])])
        return "unmatched_document"
    except Exception:
        logger.exception("Could not keep the unmatched document from %s", message.get("from_email"))
        return "no_case"


def attach_document(document_id: str, case_id: str, by: str) -> str:
    """A person says which case an unmatched document belongs to; it is then handled exactly as if it had arrived with that case's tag."""
    document = document_agent.get(document_id)
    if document["status"] != "open":
        raise DocumentAlreadyHandled(document_id)
    operations_agent.get_case_status(case_id)                       # CaseNotFound for a wrong case
    subject = document["subject"]
    message = {
        "from_email": document["from_email"],
        "subject": subject if parse_case_ref(subject) else f"RE: {REF_PREFIX}{case_id}] {subject}",
        "body": document["body"], "attachments": document["attachments"],
    }
    outcome = ingest_quote_email(message)
    if outcome in ("no_case", "not_invited", "not_accepting", "own_message", "unmatched_document"):
        raise InvalidInput("That case cannot use this document: it is not from one of its suppliers, or it is no longer waiting for one.")
    document_agent.mark_attached(document_id, case_id, by)
    operations_agent.publish_event(
        case_id, "document.attached", agent_name="Operations Agent",
        payload={"by": by, "from": document["from_email"], "subject": document["subject"], "result": outcome},
    )
    return outcome


def dismiss_document(document_id: str, by: str, note: str | None) -> None:
    document_agent.dismiss(document_id, by, note)


_PO_NUMBER = re.compile(r"\bPO[- ]?(\d{3,8})\b", re.IGNORECASE)


def _case_from_po_number(message: dict) -> str | None:
    """No case tag in the subject (a fresh email, a forwarded PDF): find the order from the purchase order number written in the
    email or the document. Only when it comes from that order's own supplier address, so nobody can attach a document to someone
    else's order by quoting its number."""
    text = " ".join([message.get("subject") or "", message.get("body") or "", *((a.get("text") or "") for a in message.get("attachments", []))])
    for number in dict.fromkeys(_PO_NUMBER.findall(text)):
        found = purchase_order_agent.find_case_for_po_number(int(number), message.get("from_email") or "")
        if found:
            return found
    return None


def _points_at_unread_file(message: dict, pictures: list[str], text: str) -> bool:
    """The words only point at a file nobody could read ("quote attached" and a locked or damaged PDF or picture): that is an unreadable
    document, not a reply without a price. A file type we never read (zip, Word) has its own rule, and words that state an amount stand alone."""
    if pictures or supplier_documents.has_price(text):
        return False
    unread = set(attachments.unreadable_names(message.get("attachments", [])))
    return bool(unread - set(supplier_documents.unsupported_files(message.get("attachments", []))))


def _page_pictures(message: dict) -> list[str]:
    """Page pictures of the attachments that have no readable text (a scan, a photo), for the AI to look at. Few, to keep the cost down."""
    if not settings.PDF_VISION_ENABLED:
        return []
    return attachments.collect_images(message.get("attachments", []), settings.PDF_VISION_MAX_PAGES)


_MAX_RESEND_ASKS = 2


@contextmanager
def _reading(case_id: str, message: dict, team: str):
    """Show the live reading status of a supplier's document on the case: document.received, document.reading, then document.read with the
    outcome (matched, needs_person, other). The block may set outcome["state"] / ["reason"]; the default is "matched". If the read fails the
    case says "needs a person" and the department is told BEFORE the error carries on, so it can never sit on "reading". A mail with no
    attachment is not a document: nothing is shown. Showing the status must never break the real work."""
    files = [a.get("name") for a in message.get("attachments") or []]
    outcome: dict = {}
    if not files:
        yield outcome
        return
    _signal_document(case_id, "document.received", {"from": message.get("from_email"), "files": files})
    _signal_document(case_id, "document.reading", {"files": files})
    try:
        yield outcome
    except Exception as exc:
        _signal_document(case_id, "document.read", {"files": files, "outcome": "needs_person", "reason": f"Reading failed: {str(exc)[:150]}"})
        try:
            notification_agent.notify_case_stalled(case_id, f"A document from the supplier ({', '.join(files)}) could not be read: {str(exc)[:150]}. "
                                                            f"Please open the email and enter the details by hand.", team=team)
        except Exception:
            logger.exception("Could not tell anyone the document on case %s failed to read", case_id)
        raise
    _signal_document(case_id, "document.read", {"files": files, "outcome": outcome.get("state", "matched"), "reason": outcome.get("reason")})


def _signal_document(case_id: str, event_type: str, payload: dict) -> None:
    try:
        operations_agent.publish_event(case_id, event_type, agent_name="Vendor Agent", payload=payload)
    except Exception:
        logger.exception("Could not record %s for case %s", event_type, case_id)


def _flag_unreadable_document(case_id: str, message: dict, vendor_id: str, team: str) -> None:
    """A supplier sent a document nobody could read. Never silent: the case says so, the right team is told, and the supplier is asked
    (at most twice per case) for a version we can read."""
    why = _unreadable_reason(message)
    files = attachments.unreadable_names(message.get("attachments", []))
    operations_agent.publish_event(
        case_id, "document.unreadable", agent_name="Vendor Agent",
        payload={"from": message["from_email"], "files": files, "reason": why},
    )
    if message.get("attachments"):                      # (a mail with only unreadable words is not a document)
        _signal_document(case_id, "document.read", {"files": files, "outcome": "needs_person", "reason": why})
    try:
        vendor = next((v for v in vendor_agent.get_all_vendors() if v["vendor_id"] == vendor_id), None)
        name = vendor["name"] if vendor else message["from_email"]
        notification_agent.notify_case_stalled(
            case_id, f"{name} sent a document that could not be read ({', '.join(files) or 'no readable text'}). "
                     f"Please open the email, read it, and enter the details by hand (or ask them to resend).", team=team)
        asked = sum(1 for e in operations_agent.get_case_events(case_id) if e["event_type"] == "document.resend_requested")
        if asked < _MAX_RESEND_ASKS:
            invoice_agent.ask_to_resend(case_id, message["from_email"], name)
    except Exception:
        logger.exception("Could not tell anyone about the unreadable document on case %s", case_id)


def _unreadable_reason(message: dict) -> str:
    unreadable = attachments.unreadable_names(message.get("attachments", []))
    if unreadable:
        return (f"Could not read the attachment(s) {', '.join(unreadable)} (scanned, password-protected "
                f"or an unsupported type). Please open the email and enter the details by hand.")
    return "Reply had no readable text."


# Once an order exists, a vendor's reply is an invoice, a confirmation or a delivery update.
# "completed" is included on purpose: an invoice arriving after the case closed is most likely a
# duplicate, and must be flagged to a person rather than silently ignored.
_PO_STAGES = frozenset({"po_issued", "po_send_failed", "po_failed", "delivery_late", "delivered", "completed", "cancel_pending"})


def _ingest_po_reply(case_id: str, vendor_id: str, message: dict) -> str:
    """A vendor wrote back about an existing order. Invoices are matched; anything else is just logged."""
    po = purchase_order_agent.find_purchase_order(case_id)
    body = _reply_text(message)
    pictures = _page_pictures(message)             # a scanned invoice is read even when the mail has a cover note
    reason = None
    if po is None or po["vendor_id"] != vendor_id:
        reason = "Sender is not the vendor on this case's purchase order."
    elif not body and not pictures:
        reason = _unreadable_reason(message)
    if reason:
        operations_agent.publish_event(
            case_id, "quote.email_ignored", agent_name="Vendor Agent",
            payload={"from": message["from_email"], "reason": reason},
        )
        if po is not None and po["vendor_id"] == vendor_id:
            _flag_unreadable_document(case_id, message, vendor_id, team="invoice")
        return "not_accepting" if po is None or po["vendor_id"] != vendor_id else "empty"

    if _points_at_unread_file(message, pictures, body):
        _flag_unreadable_document(case_id, message, vendor_id, team="invoice")
        return "empty"

    if supplier_documents.is_own_purchase_order(body, po["po_number"]):
        return _react_to_returned_order(case_id, po, message)

    if po.get("cancel_requested_at"):
        return _react_to_cancel_reply(case_id, po, body, message["from_email"])

    if supplier_documents.is_credit_note(body):
        return _react_to_credit_note(case_id, po, body, message)
    if supplier_documents.is_proforma_invoice(body):
        return _react_to_proforma(case_id, po, message)

    was_closed = (operations_agent.get_case_status(case_id) or {}).get("stage") == "completed"       # judged BEFORE this invoice can close it
    try:
        text = body or "(scanned document: read from the page pictures)"
        with _reading(case_id, message, team="invoice") as outcome:
            invoice = process_invoice(case_id, text, source="email", images=pictures) if pictures else process_invoice(case_id, text, source="email")
            outcome["state"] = "matched" if invoice and invoice.get("status") in ("matched", "partial") else "needs_person"
            outcome["reason"] = None if outcome["state"] == "matched" else "The invoice needs a person to look at it."
    except NotAnInvoice:
        if delivery_agent.note_supplier_reply(case_id, body, message["from_email"]):
            return "goods_issue_reply"                  # about the faulty goods: recorded for the person handling it
        return _react_to_order_reply(case_id, po, body, message["from_email"], has_document=bool(message.get("attachments")))
    if invoice and was_closed:
        operations_agent.publish_event(case_id, "invoice.after_close", agent_name="Invoice Agent",
                                       payload={"po_number": po["po_number"], "invoice_number": invoice.get("invoice_number"), "from": message["from_email"]})
        notification_agent.notify_case_stalled(
            case_id, f"{po['vendor_name']} sent invoice {invoice.get('invoice_number') or '(no number)'} for {po['po_number']} AFTER the request was closed. "
                     f"It may be a duplicate of one already paid. Please check before paying.", team="invoice")
    return "invoiced" if invoice else "vendor_reply"


def _react_to_returned_order(case_id: str, po: dict, message: dict) -> str:
    """The supplier sent our own purchase order back with nothing added. Never silent: the case says so, the PO desk is told (the first
    time), and the supplier is asked once what they meant. A second copy is logged but does not ask or alert again, so it cannot loop."""
    again = any(e["event_type"] == "po.returned_unchanged" for e in operations_agent.get_case_events(case_id))
    files = [a["name"] for a in message.get("attachments", [])]
    asked = False if again else purchase_order_agent.ask_what_was_meant(po)
    operations_agent.publish_event(case_id, "po.returned_unchanged", agent_name="PO Agent",
                                   payload={"po_number": po["po_number"], "from": message["from_email"], "files": files, "asked": asked, "repeat": again})
    if not again:
        notification_agent.notify_case_stalled(
            case_id, f"{po['vendor_name']} sent back our own purchase order {po['po_number']} with nothing added. "
                     f"{'We asked them what they meant. ' if asked else 'They could not be asked by email, so please contact them. '}"
                     f"Please read what they sent and see that the order is confirmed.", team="po")
    return "own_po_returned"


def _react_to_credit_note(case_id: str, po: dict, body: str, message: dict) -> str:
    """The supplier is giving money back. It is not an invoice (matching it would flag a mismatch), so it is logged with its amount when
    one is clearly stated, and Accounts is told to apply it. The payable is not changed automatically: that is money, and a person confirms it."""
    amount = supplier_documents.credit_amount(body)
    operations_agent.publish_event(case_id, "invoice.credit_note", agent_name="Invoice Agent",
                                   payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "from": message["from_email"], "amount": amount,
                                            "files": [a["name"] for a in message.get("attachments", [])]})
    how_much = f" for Rs {amount:,.2f}" if amount is not None else " (the amount could not be read: please open it)"
    notification_agent.notify_case_stalled(
        case_id, f"{po['vendor_name']} sent a credit note{how_much} against {po['po_number']}. It reduces what we owe them. "
                 f"Please read it and take it off the payment.", team="invoice")
    return "credit_note"


def _react_to_proforma(case_id: str, po: dict, message: dict) -> str:
    """A proforma invoice is not a bill. It is not matched or paid; the supplier is asked once for the final invoice and Accounts is told."""
    again = any(e["event_type"] == "invoice.proforma" for e in operations_agent.get_case_events(case_id))
    asked = False if again else invoice_agent.ask_for_final_invoice(case_id, po.get("vendor_email"), po["vendor_name"], po["po_number"])
    operations_agent.publish_event(case_id, "invoice.proforma", agent_name="Invoice Agent",
                                   payload={"po_number": po["po_number"], "vendor": po["vendor_name"], "from": message["from_email"], "asked": asked, "repeat": again})
    if not again:
        notification_agent.notify_case_stalled(
            case_id, f"{po['vendor_name']} sent a proforma invoice for {po['po_number']}. It is not a bill, so nothing was matched or paid. "
                     f"{'They were asked for the final invoice.' if asked else 'They could not be asked by email, so please ask them for the final invoice.'}",
            team="invoice")
    return "proforma"


def _react_to_new_price(case_id: str, po: dict, price: dict, body: str, sender: str) -> str:
    """The supplier states a different total price for the order. A lower price is taken; a higher one goes to an approver
    and nothing about the order changes until they decide."""
    new_total = price["new_total"]
    if price["action"] == "lower":
        purchase_order_agent.apply_lower_price(case_id, new_total, po["total_amount"])
        _acknowledge_quietly(case_id, via="email", sender=sender)
        return "po_price_lowered"
    reason = price_change.reason(po["vendor_name"], po["po_number"], po["total_amount"], new_total, price["pct"])
    approval = approval_agent.request_price_change(case_id, reason)
    purchase_order_agent.record_price_proposal(case_id, new_total, price["pct"], approval["approval_id"], body, sender)
    selection = vendor_agent.get_vendor_selection(case_id)
    notification_agent.notify_approval_needed(case_id, selection["vendor_name"], reason, approval["reasons"], approval_id=approval["approval_id"],
                                              amount=new_total, kind="price_change", summary=reason, **_email_review(approval))
    return "po_price_change"


def approval_review(approval_id: str) -> dict:
    """The whole picture for one decision (request, every supplier's reply, the AI's ranking and reasons), as a plain dict.
    Shown in the app and written into the approval email."""
    from app.core.approval_review import build_review
    from app.core.exceptions import VendorSelectionNotFound
    from app.core.price_review import build_price_review
    approval = approval_agent.get_approval(approval_id)
    case_id = approval["case_id"]
    if approval["approval_type"] == "price_change":
        return build_price_review(approval, operations_agent.get_case_status(case_id), purchase_order_agent.find_purchase_order(case_id),
                                  purchase_order_agent.proposed_price(case_id, approval_id))
    try:
        request = purchase_agent.get_purchase_request(case_id)
    except PurchaseRequestNotFound:
        request = None
    try:
        selection = vendor_agent.get_vendor_selection(case_id)
    except VendorSelectionNotFound:
        selection = None
    return build_review(
        approval, operations_agent.get_case_status(case_id), request, vendor_agent.get_quotes(case_id),
        {v["vendor_id"]: v for v in vendor_agent.get_all_vendors()}, selection, operations_agent.get_case_events(case_id),
        max_rounds=settings.RESOURCE_MAX_ROUNDS, preferred_vendor_ids=_preferred_for(request or {}))


def _email_review(approval: dict) -> dict:
    """The details to write into an approval email. If they cannot be gathered the email still goes, just shorter."""
    try:
        return {"review": approval_review(approval["approval_id"])}
    except Exception:
        logger.exception("Could not gather the details for the approval email")
        return {}


def _one_tap_context(approval: dict) -> dict:
    """What the email needs to offer one-tap buttons: which approval, how much money, and what kind. If the amount cannot be
    worked out, no buttons are offered (the approver uses the app), which is the safe way to fail."""
    try:
        case_id = approval["case_id"]
        if approval.get("approval_type") == "price_change":
            proposal = purchase_order_agent.proposed_price(case_id, approval["approval_id"])
            return {"approval_id": approval["approval_id"], "kind": "price_change",
                    "amount": tax.cost(proposal["new_total"], settings.TAX_RATE_PCT, settings.TAX_INCLUDED_IN_QUOTES) if proposal else None,
                    "summary": (approval.get("reasons") or [None])[0]}
        selection = vendor_agent.get_vendor_selection(case_id)
        quote = next((q for q in quote_rules.latest_per_vendor(vendor_agent.get_quotes(case_id)) if q["vendor_id"] == selection["vendor_id"]), None)
        return {"approval_id": approval["approval_id"], "kind": "vendor_selection",
                "amount": tax.cost(quote["price"], settings.TAX_RATE_PCT, settings.TAX_INCLUDED_IN_QUOTES) if quote else None}
    except Exception:
        logger.exception("Could not work out the amount for the approval email, so it carries no buttons")
        return {}


def _apply_price_decision(approval: dict, approve: bool, decided_by: str, note: str | None) -> None:
    case_id = approval["case_id"]
    proposal = purchase_order_agent.proposed_price(case_id, approval["approval_id"])
    if proposal is None:
        raise InvalidInput("The price the supplier asked for could not be found for this decision.")
    if approve:
        purchase_order_agent.apply_price_change(case_id, proposal["new_total"], decided_by, note)
        _acknowledge_quietly(case_id, via="price_change", by=decided_by)
    else:
        purchase_order_agent.reject_price_change(case_id, proposal["new_total"], decided_by, note)


def _react_to_cancel_reply(case_id: str, po: dict, body: str, sender: str) -> str:
    """The supplier answered our request to cancel the order."""
    kind = purchase_order_agent.classify_cancel_reply(body)
    if kind == "agreed":
        finish_cancellation(case_id, f"The supplier agreed to cancel {po['po_number']}.")
        return "po_cancelled"
    if kind == "refused":
        if not po.get("cancel_refused_at"):
            purchase_order_agent.record_cancellation_refused(case_id, body, sender)
            notification_agent.notify_case_stalled(
                case_id, f"{po['vendor_name']} says {po['po_number']} cannot be cancelled. Please read their reply and decide: "
                         f"settle the cancellation with them, or carry on with the order.", team="po")
        return "po_cancel_refused"
    operations_agent.publish_event(case_id, "vendor.replied", agent_name="Vendor Agent", payload={"from": sender, "snippet": body[:300]})
    return "vendor_reply"


def _acknowledge_quietly(case_id: str, **how) -> bool:
    try:
        return purchase_order_agent.acknowledge(case_id, **how)
    except Exception:
        logger.exception("Could not record the order confirmation for case %s", case_id)
        return False


_MONEY = re.compile(r"(?:Rs\.?|INR|\u20b9)\s*[\d,]{3,}", re.IGNORECASE)


def _maybe_ask_for_invoice(case_id: str, po: dict, body: str, sender: str, has_document: bool) -> None:
    """The goods are here, no invoice is on file, and the supplier has just written about money or sent a document that was not an
    invoice: ask once a day for the details we need (invoice number, order number, items, total) instead of leaving them guessing."""
    try:
        if delivery_agent.get_delivery(case_id)["delivery_status"] != "delivered" or invoice_agent.get_invoices(case_id):
            return
        if not (has_document or _MONEY.search(body)):
            return
        since = _now() - timedelta(hours=24)
        if any(e["event_type"] == "invoice.details_requested" and not (isinstance(e.get("created_at"), datetime) and e["created_at"] < since)
               for e in operations_agent.get_case_events(case_id)):
            return
        invoice_agent.ask_for_invoice_details(case_id, sender, po["vendor_name"], po.get("po_number"))
    except Exception:
        logger.exception("Could not ask the supplier for invoice details on case %s", case_id)


def _react_to_order_reply(case_id: str, po: dict, body: str, sender: str, has_document: bool = False) -> str:
    """A supplier's reply about the order that is not an invoice: a confirmation, a problem, or something else."""
    if supplier_documents.is_delivery_claim(body) and delivery_agent.get_delivery(case_id)["delivery_status"] == "pending":
        operations_agent.publish_event(case_id, "delivery.claimed_by_supplier", agent_name="Delivery Agent",
                                       payload={"from": sender, "po_number": po["po_number"], "snippet": body[:300]})
        notification_agent.notify_case_stalled(
            case_id, f"{po['vendor_name']} says {po['po_number']} has been delivered: \"{body[:200]}\". Nothing was marked received. "
                     f"Please check that the goods are really there, then confirm the delivery.", team="delivery")
        return "delivery_claimed"
    meaning = purchase_order_agent.classify_reply(body)
    price = price_change.assess(po["total_amount"], meaning.get("new_price"), settings.PRICE_CHANGE_TOLERANCE_PCT) if meaning.get("new_price") is not None else None
    if price and price["action"] in ("higher", "lower") and delivery_agent.get_delivery(case_id)["delivery_status"] == "pending":
        return _react_to_new_price(case_id, po, price, body, sender)
    if price and price["action"] == "confirm" and meaning["kind"] == "problem":
        meaning = {**meaning, "kind": "confirmed", "issue": None}          # they only restated the agreed price
    if meaning["kind"] == "confirmed" and po.get("acknowledged_at"):
        meaning = {"kind": "other", "issue": None}      # already confirmed: just a reply to read
    if meaning["kind"] == "confirmed":
        _acknowledge_quietly(case_id, via="email", sender=sender)
        return "po_confirmed"
    if meaning["kind"] == "problem":
        purchase_order_agent.record_vendor_problem(case_id, meaning["issue"], body, sender)
        notification_agent.notify_case_stalled(
            case_id, f"{po['vendor_name']} replied about {po['po_number']} and raised a problem: {meaning['issue'] or 'see their reply'}. "
                     f"Please read their reply and sort it out with them.", team="po")
        return "po_problem"
    operations_agent.publish_event(
        case_id, "vendor.replied", agent_name="Vendor Agent",
        payload={"from": sender, "snippet": body[:300]},
    )
    _maybe_ask_for_invoice(case_id, po, body, sender, has_document)
    return "vendor_reply"


def confirm_purchase_order(case_id: str, confirmed_by: str, note: str | None) -> dict:
    """A person records that the supplier confirmed the order another way (a phone call, say), or that a problem they
    raised has been sorted out. Stops the reminders and clears the alert."""
    po = purchase_order_agent.get_purchase_order(case_id)
    if not po.get("acknowledged_at"):
        purchase_order_agent.acknowledge(case_id, via="person", by=confirmed_by, note=note)   # also clears a problem
    elif po.get("vendor_issue"):
        purchase_order_agent.clear_vendor_issue(case_id, confirmed_by, note)
    return purchase_order_agent.get_purchase_order(case_id)


def track_po_confirmations() -> dict:
    """One worker tick over every emailed order the supplier has not confirmed: ask again, and tell the PO team once
    the supplier has been asked enough times with no answer."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = {"chased": 0, "escalated": 0}
    for po in purchase_order_agent.get_unconfirmed():
        action = next_confirm_action(po, now, settings.PO_CONFIRM_HOURS, settings.PO_CONFIRM_MAX_CHASES)
        if action == "chase":
            with operations_agent.working(po["case_id"], "chase_po_confirmation"):
                if purchase_order_agent.chase_confirmation(po):
                    counts["chased"] += 1
        elif action == "escalate":
            purchase_order_agent.mark_confirmation_overdue(po)
            notification_agent.notify_case_stalled(
                po["case_id"],
                f"{po['vendor_name']} has not confirmed {po['po_number']} after {po['confirm_chase_count']} reminder(s). "
                f"Please contact them to make sure they received the order.", team="po")
            counts["escalated"] += 1
    return counts


def _billable(po: dict, credit: float) -> dict:
    """The order as the invoice is compared with it: its total (WITH tax when the order has tax lines) less any credit agreed for faulty goods."""
    order_tax = tax.of_order(po)
    base = order_tax["total_with_tax"] if order_tax else po["total_amount"]
    return {**po, "total_amount": base - credit} if base is not None and (credit or order_tax) else po


def process_invoice(case_id: str, raw_text: str, source: str, images: list[str] | None = None) -> dict:
    """Read a vendor invoice and three-way match it against the order and the receipt.
    Clean matches close the case on their own; anything off is flagged to a person.
    Raises NotAnInvoice if the text is not an invoice."""
    po = purchase_order_agent.get_purchase_order(case_id)  # PurchaseOrderNotFound if none
    with operations_agent.working(case_id, "read_invoice"):
        extracted = invoice_agent.extract(raw_text, images) if images else invoice_agent.extract(raw_text)
    if not extracted["is_invoice"]:
        raise NotAnInvoice()
    if source == "email":
        # An invoice for the order arriving from the supplier shows they have it, so that counts as confirming it.
        _acknowledge_quietly(case_id, via="invoice", sender=po.get("vendor_email"))

    with operations_agent.working(case_id, "match_invoice"):
        delivery = delivery_agent.get_delivery(case_id)
        received = delivery["delivery_status"] == "delivered"
        problems = delivery_agent.get_issues(case_id)
        credit = goods_issues.credit_total(problems)
        billable = _billable(po, credit)                    # money agreed back comes off; with tax tracked, the order's total WITH tax is what is billed
        status, issues = evaluate_invoice(
            billable, extracted, received,
            is_duplicate=invoice_agent.number_exists(po["vendor_id"], extracted["invoice_number"]),
            tolerance_pct=settings.INVOICE_AMOUNT_TOLERANCE_PCT,
            partial=_partial_context(billable, delivery, invoice_agent.get_invoices(case_id)),
            order_tax=tax.of_order(po),
        )
        if status == "matched" and goods_issues.open_issues(problems):
            status, issues = "on_hold", ["A problem with the goods is still open, so payment is held until it is sorted out."]
        invoice = invoice_agent.record(case_id, po, raw_text, extracted, status, issues, source)

    if status == "mismatch":
        notification_agent.notify_case_stalled(
            case_id,
            f"Invoice {extracted['invoice_number'] or '(unreadable number)'} from {po['vendor_name']} "
            f"does not match {po['po_number']}: " + " ".join(issues),
            team="invoice",
        )
    elif status == "matched":
        _finalise(case_id)
    return invoice


def decide_invoice(invoice_id: str, approve: bool, decided_by: str, note: str | None) -> dict:
    """A person resolves an invoice the agent could not clear."""
    invoice = invoice_agent.decide(invoice_id, approve, decided_by, note)
    if approve:
        _finalise(invoice["case_id"])
    else:
        vendor = next((v for v in vendor_agent.get_all_vendors() if v["vendor_id"].lower() == invoice["vendor_id"].lower()), None)
        invoice_agent.request_corrected_invoice(invoice, vendor["email"] if vendor else None, note)
    return invoice


def _cleared_total(invoices: list[dict]) -> float:
    return sum(i["total_amount"] or 0 for i in invoices if i["status"] in ("matched", "approved"))


def _partial_context(po: dict, delivery: dict, invoices: list[dict]) -> dict | None:
    """Only an order delivered in parts (or already billed in parts) is matched differently; otherwise None."""
    billed = _cleared_total(invoices)
    short = bool(delivery.get("short_closed_at"))
    if not (delivery.get("partial") or short or billed > 0):
        return None
    return {"received_units": delivery["received_units"], "ordered_units": delivery["ordered_units"],
            "invoiced_so_far": billed, "closed_short": short}


def _finalise(case_id: str) -> None:
    """Close the case once the goods are received AND an invoice has been cleared (by the agent
    or by a person). Safe to call any time: it does nothing until both are true. An order that came in parts also
    needs the cleared invoices to cover what was delivered."""
    delivery = delivery_agent.get_delivery(case_id)
    if delivery["delivery_status"] != "delivered":
        return
    if goods_issues.open_issues(delivery_agent.get_issues(case_id)):
        return                                          # a problem with the goods is still open
    invoices = invoice_agent.get_invoices(case_id)
    if delivery.get("short_closed_at") or len(delivery.get("batches", [])) > 1:
        po = purchase_order_agent.get_purchase_order(case_id)
        if po["total_amount"] is not None:
            share = delivery["received_units"] / max(1, delivery["ordered_units"])
            if _cleared_total(invoices) < po["total_amount"] * share * (1 - settings.INVOICE_AMOUNT_TOLERANCE_PCT / 100):
                return                      # delivered in parts and not yet billed in full for what arrived
    if any(i["status"] in ("matched", "approved") for i in invoices):
        operations_agent.close_case(
            case_id, stage="completed",
            reason="Goods received and the invoice was cleared for payment.",
        )


def advance_sourcing(case_id: str) -> str:
    """One worker tick for a case that is waiting on vendor quotes.
    Returns the action taken: rank | stalled | remind | wait."""
    rfqs = vendor_agent.get_rfqs(case_id)
    quote_count = len(vendor_agent.get_quotes(case_id))
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Only a quiet request is worth the extra read: the interval matters just when a reminder could be due.
    request = purchase_agent.get_purchase_request(case_id) if any(r["status"] != "replied" for r in rfqs) else None
    interval = urgency.pick(bool(request and request.get("urgent")), settings.RFQ_REMINDER_HOURS, settings.URGENT_REMINDER_HOURS)
    action, rfq_ids = next_sourcing_action(
        rfqs, quote_count, now,
        interval, settings.RFQ_MAX_REMINDERS,
    )

    if action == "rank":
        rank_and_review(case_id, negotiate=True)
    elif action == "stalled":
        answered = bool(rfqs) and all(r["status"] in ("replied", "bounced", "withdrawn") for r in rfqs) and any(r["status"] == "replied" for r in rfqs)
        stalled_reason = ("Every supplier has answered, but none gave a price (they declined or replied without one)." if answered
                          else "No vendor quotes were received before the deadline.")
        operations_agent.publish_event(
            case_id, "sourcing.stalled", agent_name="Operations Agent",
            payload={"reason": stalled_reason},
        )
        operations_agent.set_stage(case_id, "sourcing_stalled")
        notification_agent.notify_case_stalled(case_id, stalled_reason, team="vendor")
    elif action == "remind":
        with operations_agent.working(case_id, "remind_suppliers"):
            vendor_agent.send_reminders(case_id, request["items"], rfq_ids)

    return action


def rank_and_review(case_id: str, negotiate: bool = False) -> dict:
    """Rank quotes, then run the approval policy. Routine selections are
    auto-approved; only exceptions stop at 'awaiting_approval' for a human. With `negotiate` (the first ranking of a round, and only when it is
    switched on) the chosen supplier is first asked once for a better price and the case waits for the answer (see _start_negotiation)."""
    needed_by = purchase_agent.get_purchase_request(case_id).get("needed_by")
    with operations_agent.working(case_id, "rank_quotes"):
        vendor_agent.rank_vendors(case_id, needed_by)
    if negotiate and _start_negotiation(case_id):
        return vendor_agent.get_vendor_selection(case_id)
    return _review_selection(case_id, needed_by)


def _review_selection(case_id: str, needed_by) -> dict:
    """The approval policy for the chosen supplier, then whatever follows (a person is asked, or the order goes out)."""
    with operations_agent.working(case_id, "review_approval"):
        approval = approval_agent.review_vendor_selection(case_id, needed_by)
    selection = vendor_agent.get_vendor_selection(case_id)
    if approval["status"] == "pending":
        check_approver_cover(case_id, approval.get("approval_id"))
        notification_agent.notify_approval_needed(
            case_id, selection["vendor_name"], selection["rationale"], approval["reasons"], **_one_tap_context(approval), **_email_review(approval),
        )
    elif approval["status"] == "auto_approved":
        _issue_purchase_order_safely(case_id)
    return selection


def _chosen_price(case_id: str, vendor_id: str) -> float | None:
    quote = next((q for q in quote_rules.latest_per_vendor(vendor_agent.get_quotes(case_id)) if q["vendor_id"] == vendor_id), None)
    return quote["price"] if quote else None


def _start_negotiation(case_id: str) -> bool:
    """Ask the chosen supplier ONCE for a better price and make the case wait for the answer. True when the case now waits. Never raises: if
    anything goes wrong the original quote simply goes on to approval."""
    try:
        if not settings.NEGOTIATE_ENABLED:
            return False
        selection = vendor_agent.get_vendor_selection(case_id)
        price = _chosen_price(case_id, selection["vendor_id"])
        vendor = next((v for v in vendor_agent.get_all_vendors() if v["vendor_id"].lower() == selection["vendor_id"].lower()), None)
        events = operations_agent.get_case_events(case_id)
        why_not = negotiation.should_ask(True, events, price, (vendor or {}).get("email"))
        if why_not is not None:
            if why_not == "no e-mail address":
                operations_agent.publish_event(case_id, "negotiation.skipped", agent_name="Vendor Agent", payload={"vendor": selection["vendor_name"], "reason": why_not})
            return False
        items = purchase_agent.get_purchase_request(case_id)["items"]
        if not vendor_agent.ask_better_price(case_id, selection["vendor_id"], items, price, settings.NEGOTIATE_WAIT_HOURS):
            operations_agent.publish_event(case_id, "negotiation.skipped", agent_name="Vendor Agent", payload={"vendor": selection["vendor_name"], "reason": "the e-mail could not be sent"})
            return False
        operations_agent.publish_event(case_id, negotiation.ASKED, agent_name="Vendor Agent",
                                       payload={"vendor_id": selection["vendor_id"], "vendor": selection["vendor_name"], "original_price": price})
        operations_agent.set_stage(case_id, negotiation.STAGE)
        return True
    except Exception:
        logger.exception("Could not start the negotiation on case %s; the original quote goes on", case_id)
        return False


def _end_negotiation(case_id: str, improved: bool) -> None:
    """The answer (or the silence) is in: carry on to approval. A better price changes the quote, so the supplier is ranked again; otherwise the
    ranking already made stands and only the approval policy runs."""
    if operations_agent.get_case_status(case_id)["stage"] != negotiation.STAGE:
        return                                                                    # someone else already moved it on
    if improved:
        rank_and_review(case_id)
    else:
        _review_selection(case_id, purchase_agent.get_purchase_request(case_id).get("needed_by"))


def _ingest_negotiation_reply(case_id: str, vendor_id: str, message: dict) -> str:
    """A mail while the chosen supplier is being asked for a better price. Only THEIR answer matters; a lower price is taken, anything else
    keeps the original quote. Either way the approval rules decide next."""
    asked = negotiation.asked_this_round(operations_agent.get_case_events(case_id)) or {}
    if (asked.get("vendor_id") or "").lower() != vendor_id.lower():
        operations_agent.publish_event(case_id, "quote.email_ignored", agent_name="Vendor Agent",
                                       payload={"from": message["from_email"], "reason": "The request is being compared; a late reply from another supplier was not used."})
        return "not_accepting"
    text = _reply_text(message)
    name = asked.get("vendor") or message["from_email"]
    original = asked.get("original_price")
    if not text:
        operations_agent.publish_event(case_id, "quote.email_ignored", agent_name="Vendor Agent", payload={"from": message["from_email"], "reason": _unreadable_reason(message)})
        return "empty"
    if supplier_documents.is_question(text):
        return _react_to_question(case_id, vendor_id, message, text)               # the Vendor team answers; the wait continues
    structured = None if supplier_documents.is_decline(text) else vendor_agent.read_quote(text)
    price = structured.get("price") if structured else None
    kind = negotiation.verdict(original, price)
    if kind == "improved":
        vendor_agent.submit_quote(case_id, vendor_id, text, structured=structured)
        operations_agent.publish_event(case_id, "negotiation.improved", agent_name="Vendor Agent",
                                       payload={"vendor": name, "old_price": original, "new_price": price, "summary": negotiation.summary(original, price)})
    else:
        operations_agent.publish_event(case_id, "negotiation.no_improvement", agent_name="Vendor Agent",
                                       payload={"vendor": name, "old_price": original, "reply_price": price, "why": kind})
        if kind == "suspicious":
            notification_agent.notify_case_stalled(case_id, f"{name} replied to the request for a better price with {price:,.2f}, far below their {original:,.2f}. "
                                                            f"That looks like a misreading, so the original quote was kept. Please read their reply.", team="vendor")
    _end_negotiation(case_id, improved=kind == "improved")
    return "negotiated" if kind == "improved" else "negotiation_kept"


def track_negotiations() -> int:
    """One worker pass: a supplier who has not answered the request for a better price in time is left with their original quote and the case
    goes on to approval. Returns how many were moved on."""
    now = _now()
    moved = 0
    for case in operations_agent.get_all_cases(None):
        if case["status"] != "open" or case["stage"] != negotiation.STAGE:
            continue
        asked = negotiation.asked_this_round(operations_agent.get_case_events(case["case_id"]))
        if asked is None or not negotiation.is_due(asked.get("at"), now, settings.NEGOTIATE_WAIT_HOURS):
            continue
        try:
            operations_agent.publish_event(case["case_id"], "negotiation.no_reply", agent_name="Vendor Agent",
                                           payload={"vendor": asked.get("vendor"), "original_price": asked.get("original_price")})
            _end_negotiation(case["case_id"], improved=False)
            moved += 1
        except Exception:
            logger.exception("Could not move case %s on after the negotiation wait", case["case_id"])
    return moved


def decide_approval(approval_id: str, approve: bool, decided_by: str, note: str | None,
                    re_source: bool = False, skip_selected: bool = False) -> dict:
    """A human's decision. Approval moves the case straight on to the purchase order. A rejection ends the request,
    unless the approver asked for new quotes: then the suppliers are asked again (up to RESOURCE_MAX_ROUNDS times)."""
    existing = approval_agent.get_approval(approval_id)
    if existing.get("approval_type") == "price_change":              # a supplier's higher price: it never touches the case's stage
        result = approval_agent.decide(approval_id, approve, decided_by, note)
        _apply_price_decision(result, approve, decided_by, note)
        return result
    re_source = re_source and not approve
    if re_source:
        case_id = approval_agent.get_approval(approval_id)["case_id"]
        events = operations_agent.get_case_events(case_id)
        if not resource_policy.can_resource(events, settings.RESOURCE_MAX_ROUNDS):
            raise InvalidInput(
                f"This request has already been sent back for new quotes {resource_policy.rounds_used(events)} time(s), "
                f"which is the limit. Choose one of the suppliers, or reject it for good.")
        selection = vendor_agent.get_vendor_selection(case_id)
        round_no = resource_policy.round_number(events) + 1
    result = (approval_agent.decide(approval_id, approve, decided_by, note, re_sourcing=True) if re_source
              else approval_agent.decide(approval_id, approve, decided_by, note))
    if approve:
        _issue_purchase_order_safely(result["case_id"])
    elif re_source:
        request = purchase_agent.get_purchase_request(case_id)
        with operations_agent.working(case_id, "request_quotes"):
            invited = vendor_agent.restart_sourcing(case_id, request["items"], round_no, selection["vendor_id"] if skip_selected else None, **_terms(request))
        calling_agent.notify_email_sent(case_id, invited, "rfq")
        if not invited:
            notification_agent.notify_case_stalled(
                case_id, "The suppliers could not be asked again (none has an email address, or sending failed).", team="vendor")
    return result


def issue_purchase_order(case_id: str) -> dict:
    """Create the PO for an approved vendor and email it. Idempotent: one PO per case, and
    calling again only retries the email if the earlier send failed."""
    # The newest decision about the supplier is the one that counts (the repository lists newest first); an earlier "approved"
    # must not let an order go out after the offers were turned down or replaced.
    decisions = [a for a in approval_agent.get_approvals(case_id=case_id)
                 if a.get("approval_type", "vendor_selection") == "vendor_selection" and a["status"] != "superseded"]
    if not decisions or decisions[0]["status"] not in ("approved", "auto_approved"):
        raise VendorNotApproved(case_id)

    selection = vendor_agent.get_vendor_selection(case_id)
    vendor = next(v for v in vendor_agent.get_all_vendors() if v["vendor_id"] == selection["vendor_id"])

    po = purchase_order_agent.find_purchase_order(case_id)
    if po and po["status"] == "sent":
        return po

    if po:
        with operations_agent.working(case_id, "issue_po"):
            po = purchase_order_agent.resend(case_id, vendor)
    else:
        quote = next((q for q in quote_rules.latest_per_vendor(vendor_agent.get_quotes(case_id)) if q["vendor_id"] == vendor["vendor_id"]), None)
        request = purchase_agent.get_purchase_request(case_id)
        items = request["items"]
        if quote and quote_expiry.is_expired(quote, _now()):
            # The approval waited longer than the supplier's price is valid. Never order at a price they no longer stand behind.
            with operations_agent.working(case_id, "request_quotes"):
                vendor_agent.request_quote_refresh(case_id, vendor["vendor_id"], items, quote["valid_until"], **_terms(request))
            notification_agent.notify_case_stalled(
                case_id, f"{vendor['name']}'s quotation expired on {quote['valid_until']:%d %b %Y} before the order could be placed, so they were asked to "
                         f"confirm or update their price. The order will be decided again when they reply.", team="approval")
            raise QuoteExpired(f"{vendor['name']}'s quotation expired on {quote['valid_until']:%d %b %Y}. They have been asked to refresh it.")
        with operations_agent.working(case_id, "issue_po"):
            po = purchase_order_agent.create_and_send(case_id, vendor, quote, items)

    if po["status"] == "sent":
        calling_agent.notify_email_sent(case_id, [vendor["name"]], "po")
        operations_agent.set_stage(case_id, "po_issued")
    else:
        operations_agent.set_stage(case_id, "po_send_failed")
        notification_agent.notify_case_stalled(
            case_id,
            f"{po['po_number']} was created but could not be emailed to {vendor['name']} "
            f"(no email address on file, or sending failed). Fix the vendor and retry the purchase order.",
            team="po",
        )
    return po


def short_close_delivery(case_id: str, closed_by: str, note: str | None) -> dict:
    """The supplier will not send the rest and a person accepts that: the order counts as delivered as it stands."""
    result = delivery_agent.short_close(case_id, closed_by, note)
    operations_agent.set_stage(case_id, "delivered")
    for invoice in invoice_agent.get_invoices(case_id):
        if invoice["status"] == "on_hold":
            invoice_agent.re_evaluate(invoice, "mismatch", ["The order was closed short, so this invoice for the full amount needs a person to check it."])
    _finalise(case_id)
    return result


# ---------------------------------------------------------------------------------------------
# Cancel or change a request

def cancel_options(case_id: str) -> dict:
    case = operations_agent.get_case_status(case_id)
    po = purchase_order_agent.find_purchase_order(case_id)
    delivery = None
    if po and po["status"] == "sent":
        delivery = delivery_agent.get_delivery(case_id)
    result = change_policy.options(case, po, delivery, operations_agent.get_case_events(case_id))
    result["items"] = []
    if result["can_change"]:
        try:
            result["items"] = purchase_agent.get_purchase_request(case_id)["items"]
        except PurchaseRequestNotFound:        # the request was never read, so there is nothing to change
            result["can_change"] = False
    return result


def finish_cancellation(case_id: str, reason: str) -> None:
    """Close the case as cancelled (the order, if any, is marked cancelled too)."""
    po = purchase_order_agent.find_purchase_order(case_id)
    if po and po["status"] != "cancelled":
        purchase_order_agent.mark_cancelled(case_id)
    operations_agent.publish_event(case_id, "case.cancelled", agent_name="Operations Agent", payload={"reason": reason})
    operations_agent.close_case(case_id, stage="cancelled", reason=reason)


def cancel_case(case_id: str, by: str, reason: str | None) -> dict:
    """Cancel a request. Before an order goes out it ends at once and the suppliers who were asked are told;
    once the supplier has the order we ask them to cancel and wait for their answer."""
    opt = cancel_options(case_id)
    if not opt["can_cancel"]:
        raise InvalidInput(opt["note"])
    why = (reason or "").strip()[:500] or None
    if opt["phase"] == "from_stock":
        return _cancel_from_stock(case_id, by, why)
    if opt["phase"] == "before_order":
        with operations_agent.working(case_id, "withdraw_request"):
            told = vendor_agent.withdraw_rfqs(case_id, None)       # (the reason is the requester's own business, not the supplier's)
            approval_agent.withdraw_pending(case_id)
        finish_cancellation(case_id, f"Cancelled by {by}" + (f": {why}" if why else "."))
        return {"outcome": "cancelled", "suppliers_told": told}
    po = purchase_order_agent.request_cancellation(case_id, by, why)
    operations_agent.set_stage(case_id, "cancel_pending")
    notification_agent.notify_case_stalled(
        case_id, f"{by} cancelled the request, so the supplier {po['vendor_name']} was asked to cancel {po['po_number']}"
                 + (f" ({why})" if why else "") + ". We are waiting for their answer.", team="po")
    return {"outcome": "cancelling", "suppliers_told": [po["vendor_name"]]}


def _cancel_from_stock(case_id: str, by: str, why: str | None) -> dict:
    """A request that was filled from the shelf is cancelled: what it took goes back on the stock count (recorded against the case), and
    Stores is told to check the goods were not already handed over. Never silent: the case says what went back, or why nothing did."""
    events = operations_agent.get_case_events(case_id)
    taken = agent_cases.stock_taken(events)
    returned, unmatched = [], {}
    if taken:
        result = procurement_agent.return_to_stock(case_id, taken, by)
        returned, unmatched = result["returned"], result["unmatched"]
    operations_agent.publish_event(case_id, "stock.returned", agent_name="Procurement Agent",
                                   payload={"items": returned, "unmatched": unmatched, "by": by})
    finish_cancellation(case_id, f"Cancelled by {by}" + (f": {why}" if why else "."))
    items = ", ".join(f"{r['item']} x {r['returned']}" for r in returned) or "nothing"
    notification_agent.notify_case_stalled(
        case_id, f"{by} cancelled a request that was filled from stock. Put back on the count: {items}."
                 + (f" Could not put back (no such stock item any more): {', '.join(unmatched)}." if unmatched else "")
                 + " Please check the goods were not already handed over.", team="procurement")
    return {"outcome": "cancelled", "suppliers_told": []}


def resolve_cancellation(case_id: str, action: str, by: str, note: str | None) -> dict:
    """A person settles a cancellation the supplier has not answered, or refused: `settled` (it is cancelled, say by
    phone) or `carry_on` (drop the cancellation and keep the order)."""
    po = purchase_order_agent.find_purchase_order(case_id)
    if not po or po["status"] != "sent" or not po.get("cancel_requested_at"):
        raise InvalidInput("No cancellation is waiting on this order.")
    if action == "settled":
        finish_cancellation(case_id, f"Cancelled; settled with the supplier by {by}" + (f": {note}" if note else "."))
        return {"outcome": "cancelled"}
    if action == "carry_on":
        purchase_order_agent.withdraw_cancellation(case_id, by, note)
        operations_agent.set_stage(case_id, "po_issued")
        return {"outcome": "carrying_on"}
    raise InvalidInput("Choose 'settled' or 'carry_on'.")


def change_case(case_id: str, by: str, wanted: dict[str, int], note: str | None) -> dict:
    """Change quantities on a request. Before an order goes out the stock is re-checked and the suppliers are asked
    again for the new quantities; once the supplier has the order the change goes to the PO desk to agree with them."""
    opt = cancel_options(case_id)
    if not opt["can_change"]:
        raise InvalidInput(opt["note"] if opt["phase"] != "after_order" else "A change to this order is already waiting for the purchasing team.")
    try:
        changes = change_policy.plan_changes(purchase_agent.get_purchase_request(case_id)["items"], wanted)
    except change_policy.BadChange as exc:
        raise InvalidInput(str(exc)) from exc
    clean_note = (note or "").strip()[:500] or None

    if opt["phase"] == "after_order":
        purchase_order_agent.record_change_request(case_id, changes, by, clean_note)
        po = purchase_order_agent.get_purchase_order(case_id)
        notification_agent.notify_case_stalled(
            case_id, f"{by} asked to change the order {po['po_number']} with {po['vendor_name']}: {change_policy.changes_text(changes)}. "
                     f"Please agree it with the supplier and record the result.", team="po")
        return {"outcome": "passed_to_po_desk", "changes": changes}

    stage = operations_agent.get_case_status(case_id)["stage"]
    purchase_agent.change_quantities(case_id, changes, by, clean_note)
    if stage in ("created", "purchase_request_created"):
        return {"outcome": "changed", "changes": changes}
    approval_agent.withdraw_pending(case_id)
    rfqs = vendor_agent.get_rfqs(case_id)
    with operations_agent.working(case_id, "check_stock"):
        stock = procurement_agent.check_stock(case_id)              # fewer units may now be in stock (this also re-opens the sourcing stage)
    if stock["sufficient"]:
        vendor_agent.withdraw_rfqs(case_id, None)
        return {"outcome": "filled_from_stock", "changes": changes}
    if rfqs and not automation.is_paused():
        request = purchase_agent.get_purchase_request(case_id)
        rounds = sum(1 for e in operations_agent.get_case_events(case_id) if e["event_type"] == "sourcing.restarted")
        with operations_agent.working(case_id, "request_quotes"):
            invited = vendor_agent.restart_sourcing(case_id, request["items"], rounds + 2, **_terms(request))
        calling_agent.notify_email_sent(case_id, invited, "rfq")
        if not invited:
            notification_agent.notify_case_stalled(case_id, "The suppliers could not be asked again for the changed quantities.", team="vendor")
    return {"outcome": "changed", "changes": changes}


def resolve_change(case_id: str, action: str, by: str, total_amount, note: str | None) -> dict:
    """The PO desk records what happened to a quantity change on an order the supplier already had:
    `amended` (agreed: the order now carries the new quantities) or `declined` (the order stays as it was)."""
    pending = change_policy.pending_change(operations_agent.get_case_events(case_id))
    if pending is None:
        raise InvalidInput("No change is waiting on this order.")
    if action == "amended":
        if total_amount is not None and total_amount <= 0:
            raise InvalidInput("The new total must be more than zero.")
        purchase_agent.change_quantities(case_id, pending["changes"], by, note)
        purchase_order_agent.apply_change(case_id, pending["changes"], total_amount, by, note)
        return {"outcome": "amended"}
    if action == "declined":
        purchase_order_agent.decline_change(case_id, by, note)
        return {"outcome": "declined"}
    raise InvalidInput("Choose 'amended' or 'declined'.")


def track_cancellations() -> dict:
    """One worker tick over every order we asked a supplier to cancel: ask again if they are silent, and tell the PO
    team once they have been asked enough times (same pattern and timings as order confirmations)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = {"chased": 0, "escalated": 0}
    for po in purchase_order_agent.get_cancelling():
        as_confirm = {"acknowledged_at": None, "sent_at": po["cancel_requested_at"], "last_confirm_chase_at": po["last_cancel_chase_at"],
                      "confirm_chase_count": po["cancel_chase_count"], "confirm_escalated_at": po["cancel_escalated_at"],
                      "vendor_issue": "refused" if po["cancel_refused_at"] else None}
        action = next_confirm_action(as_confirm, now, settings.PO_CONFIRM_HOURS, settings.PO_CONFIRM_MAX_CHASES)
        if action == "chase":
            with operations_agent.working(po["case_id"], "chase_po_confirmation"):
                if purchase_order_agent.chase_cancellation(po):
                    counts["chased"] += 1
        elif action == "escalate":
            purchase_order_agent.mark_cancellation_overdue(po)
            notification_agent.notify_case_stalled(
                po["case_id"], f"{po['vendor_name']} has not answered our request to cancel {po['po_number']} after "
                               f"{po['cancel_chase_count']} reminder(s). Please contact them.", team="po")
            counts["escalated"] += 1
    return counts


# ---------------------------------------------------------------------------------------------
# Wrong or damaged goods

def report_goods_issue(case_id: str, kind: str, items: dict[str, int] | None, description: str | None, by: str) -> dict:
    """Receiving records a problem with goods that arrived. The supplier is asked to put it right and payment is held."""
    if operations_agent.get_case_status(case_id)["status"] != "open":
        raise InvalidInput("This request is already closed. Raise the problem with Accounts or the PO desk.")
    issue = delivery_agent.report_issue(case_id, kind, items, description, by)
    notification_agent.notify_case_stalled(
        case_id, f"{by} reported a problem with the goods on {issue['po_number']} from {issue['vendor_name']}: "
                 f"{goods_issues.affected_text(issue['items'])} {goods_issues.KINDS[kind]}. "
                 f"{'The supplier has been asked to put it right.' if issue['supplier_told_at'] else 'The supplier could NOT be emailed, please contact them.'}",
        team="delivery")
    _take_faulty_off_stock(case_id, issue, by)
    return issue


def _take_faulty_off_stock(case_id: str, issue: dict, by: str) -> None:
    """Faulty goods from a low-stock reorder were added to the shelf count when they arrived, so they come off it again (and the
    stock history says so). Goods bought for a request never touched the stock, so nothing changes for those. The problem is already
    recorded and must not fail because of this: a failure is logged and shown on the case instead."""
    try:
        if not any(e["event_type"] == "restock.requested" for e in operations_agent.get_case_events(case_id)):
            return
        result = procurement_agent.take_off_faulty(case_id, issue["items"], issue["kind"], by)
        if result["removed"]:
            operations_agent.publish_event(case_id, "stock.reduced", agent_name="Procurement Agent",
                                           payload={"items": result["removed"], "issue_id": issue.get("issue_id")})
        if result["unmatched"]:
            operations_agent.publish_event(case_id, "stock.reduce_unmatched", agent_name="Procurement Agent", payload={"items": result["unmatched"]})
    except Exception:
        logger.exception("Could not take the faulty goods of case %s off the stock count", case_id)
        operations_agent.publish_event(case_id, "stock.reduce_failed", agent_name="Procurement Agent", payload={"items": issue["items"]})


def return_goods(issue_id: str, ref: str | None, by: str) -> dict:
    """Receiving sends the faulty goods back. Stock is not touched here: goods from a low-stock reorder came off the count when the problem
    was reported, and a replacement or an accepted problem puts them back when it ends."""
    return delivery_agent.return_goods(issue_id, by, ref)


def expect_goods_replacement(issue_id: str, by: str) -> dict:
    return delivery_agent.expect_replacement(issue_id, by)


def receive_goods_replacement(issue_id: str, note: str | None, by: str) -> dict:
    """The replacement arrived: the problem ends as 'replaced', exactly as if a person had closed it that way (stock goes back, a held invoice
    is checked again, the case may finish)."""
    delivery_agent.receive_replacement(issue_id, by, note)
    return _after_issue_resolved(issue_id, "replaced", by)


def resolve_goods_issue(issue_id: str, resolution: str, credit_amount, note: str | None, by: str, credit_note_number: str | None = None) -> dict:
    """A person records how a goods problem ended. Payment is released if nothing else is holding it."""
    delivery_agent.resolve_issue(issue_id, resolution, credit_amount, note, by, credit_note_number)
    return _after_issue_resolved(issue_id, resolution, by)


def _after_issue_resolved(issue_id: str, resolution: str, by: str) -> dict:
    issue = delivery_agent.get_issue(issue_id)
    case_id = issue["case_id"]
    if resolution == "credit":
        _log_credit_for_accounts(case_id, issue)
    _put_back_stock(case_id, issue, resolution, by)
    # an invoice held for this problem now has to be checked against the amount after any credit
    credit = goods_issues.credit_total(delivery_agent.get_issues(case_id))
    po = purchase_order_agent.get_purchase_order(case_id)
    billable = _billable(po, credit)
    delivery = delivery_agent.get_delivery(case_id)
    if not goods_issues.open_issues(delivery_agent.get_issues(case_id)):
        for invoice in invoice_agent.get_invoices(case_id):
            if invoice["status"] != "on_hold" or invoice["total_amount"] is None:
                continue
            status, problems = evaluate_invoice(
                billable, {"invoice_number": invoice["invoice_number"], "total_amount": invoice["total_amount"], "po_number": invoice["po_number"], "items": [],
                          "subtotal": invoice.get("subtotal"), "tax_rate_pct": invoice.get("tax_rate_pct"), "tax_amount": invoice.get("tax_amount")},
                delivery["delivery_status"] == "delivered", False, settings.INVOICE_AMOUNT_TOLERANCE_PCT, order_tax=tax.of_order(po),
                partial=_partial_context(billable, delivery, [i for i in invoice_agent.get_invoices(case_id) if i["invoice_id"] != invoice["invoice_id"]]))
            if status != "on_hold":
                invoice_agent.re_evaluate(invoice, status, problems)
                if status == "mismatch":
                    notification_agent.notify_case_stalled(
                        case_id, f"Invoice {invoice['invoice_number'] or '(no number)'} from {po['vendor_name']} was waiting for the goods problem to be "
                                 f"sorted out and does not match what is now owed: " + " ".join(problems), team="invoice")
    _finalise(case_id)
    return issue


def _log_credit_for_accounts(case_id: str, issue: dict) -> None:
    """A credit was agreed: the case records it and Accounts are told to apply it BY HAND. Nothing owed is changed automatically (the invoice
    match already allows for it). Never raises: the problem is already closed."""
    try:
        operations_agent.publish_event(case_id, "goods.credit_logged", agent_name="Delivery Agent",
                                       payload={"issue_id": issue["issue_id"], "po_number": issue["po_number"], "vendor": issue["vendor_name"],
                                                "credit_amount": issue["credit_amount"], "credit_note_number": issue.get("credit_note_number")})
        notification_agent.notify_case_stalled(case_id, goods_issues.credit_message(issue), team="invoice")
    except Exception:
        logger.exception("Could not tell Accounts about the credit on case %s", case_id)


def _put_back_stock(case_id: str, issue: dict, resolution: str, by: str) -> None:
    """Faulty goods from a low-stock reorder were taken off the stock count when they were reported. If the problem ends with the goods
    kept ("accepted") or replaced, they come back; a supplier credit leaves them off. Only for reorders, and only what was really taken
    off for THIS problem. The resolution is already recorded and must not fail because of this: a failure is logged and shown on the case."""
    if resolution not in ("accepted", "replaced"):
        return
    try:
        events = operations_agent.get_case_events(case_id)
        if not any(e["event_type"] == "restock.requested" for e in events):
            return
        if any(e["event_type"] == "stock.restored" and (e.get("payload") or {}).get("issue_id") == issue["issue_id"] for e in events):
            return                                                   # already put back (never twice)
        taken = [i for e in events if e["event_type"] == "stock.reduced" and (e.get("payload") or {}).get("issue_id") == issue["issue_id"]
                 for i in (e.get("payload") or {}).get("items", [])]
        if not taken:
            return                                                   # nothing was taken off for this problem
        result = procurement_agent.put_back_faulty(case_id, taken, resolution, by)
        if result["restored"]:
            operations_agent.publish_event(case_id, "stock.restored", agent_name="Procurement Agent",
                                           payload={"items": result["restored"], "issue_id": issue["issue_id"], "resolution": resolution})
        if result["unmatched"]:
            operations_agent.publish_event(case_id, "stock.restore_unmatched", agent_name="Procurement Agent", payload={"items": result["unmatched"]})
    except Exception:
        logger.exception("Could not put the goods of problem %s back on the stock count", issue.get("issue_id"))
        operations_agent.publish_event(case_id, "stock.restore_failed", agent_name="Procurement Agent", payload={"issue_id": issue.get("issue_id")})


def track_goods_issues() -> dict:
    """One worker tick over every open goods problem: ask the supplier again if they have not answered, and tell the
    Receiving team once they have been asked enough times (same pattern and timings as order confirmations)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = {"chased": 0, "escalated": 0}
    for issue in delivery_agent.get_open_issues():
        as_confirm = {"acknowledged_at": issue["supplier_replied_at"], "sent_at": issue["supplier_told_at"], "last_confirm_chase_at": issue["last_chased_at"],
                      "confirm_chase_count": issue["chase_count"], "confirm_escalated_at": issue["escalated_at"], "vendor_issue": None}
        action = next_confirm_action(as_confirm, now, settings.PO_CONFIRM_HOURS, settings.PO_CONFIRM_MAX_CHASES)
        if action == "chase":
            with operations_agent.working(issue["case_id"], "chase_po_confirmation"):
                if delivery_agent.chase_issue(issue):
                    counts["chased"] += 1
        elif action == "escalate":
            delivery_agent.mark_issue_overdue(issue)
            notification_agent.notify_case_stalled(
                issue["case_id"], f"{issue['vendor_name']} has not said how they will put right the problem with {issue['po_number']} "
                                  f"after {issue['chase_count']} reminder(s). Please contact them.", team="delivery")
            counts["escalated"] += 1
    return counts


# ---------------------------------------------------------------------------------------------
# Two requests for the same item

def suggest_combines(case_id: str) -> int:
    """Note any older request that is still collecting quotes for the same item(s). A person decides whether to combine.
    Returns how many suggestions were recorded."""
    if not settings.COMBINE_SUGGESTIONS:
        return 0
    mine = operations_agent.get_case_status(case_id)
    my_items = purchase_agent.get_purchase_request(case_id)["items"]
    already = {str((e.get("payload") or {}).get("primary_case_id", "")).lower() for e in operations_agent.get_case_events(case_id)
               if e["event_type"] in (combine.SUGGESTED, combine.DISMISSED)}
    found = 0
    for other in combine.candidates(mine, operations_agent.get_all_cases(None), settings.COMBINE_WINDOW_HOURS, _now()):
        if other["case_id"].lower() in already or other["created_at"] > mine["created_at"]:
            continue                                   # (only the newer request suggests; the older one is what it would join)
        try:
            their_items = purchase_agent.get_purchase_request(other["case_id"])["items"]
        except PurchaseRequestNotFound:
            continue
        shared = combine.overlap(their_items, my_items)
        if not shared:
            continue
        operations_agent.publish_event(
            case_id, combine.SUGGESTED, agent_name="Operations Agent",
            payload={"primary_case_id": other["case_id"], "primary_number": other.get("case_number"), "matches": shared})
        found += 1
    return found


def combine_suggestions(case_id: str | None = None) -> list[dict]:
    """Suggestions still waiting for a person (optionally only those involving one request), with both request numbers."""
    cases = {c["case_id"].lower(): c for c in operations_agent.get_all_cases(None)}
    events = operations_agent.get_events_of_types((combine.SUGGESTED, combine.DISMISSED, combine.MERGED_INTO))
    out = []
    for s in combine.open_suggestions(events, cases):
        if case_id and case_id.lower() not in (s["newer"], s["older"]):
            continue
        out.append({**s, "newer_number": cases[s["newer"]].get("case_number"), "older_number": cases[s["older"]].get("case_number")})
    return out


def dismiss_combine(case_id: str, other_case_id: str, by: str) -> None:
    """A person says these two requests should stay separate: the suggestion is not made again."""
    a, b = (operations_agent.get_case_status(x) for x in (case_id, other_case_id))
    older, newer = combine.primary_of(a, b)
    operations_agent.publish_event(newer["case_id"], combine.DISMISSED, agent_name="Operations Agent",
                                   payload={"primary_case_id": older["case_id"], "by": by})


def combine_cases(case_id: str, other_case_id: str, by: str) -> dict:
    """Fold the newer of the two requests into the older: one set of quantities, suppliers asked again for the combined
    amount, and the newer request closed as combined. Only while neither has an order."""
    if case_id.lower() == other_case_id.lower():
        raise InvalidInput("A request cannot be combined with itself.")
    a, b = (operations_agent.get_case_status(x) for x in (case_id, other_case_id))
    for c in (a, b):
        if c["status"] != "open" or c["stage"] not in combine.MERGEABLE_STAGES:
            raise InvalidInput(f"{c.get('case_number') or 'A request'} can no longer be combined: it is already {c['stage'].replace('_', ' ')}.")
        if purchase_order_agent.find_purchase_order(c["case_id"]) is not None:
            raise InvalidInput(f"{c.get('case_number') or 'A request'} already has an order with a supplier.")
    older, newer = combine.primary_of(a, b)
    keep, fold = purchase_agent.get_purchase_request(older["case_id"]), purchase_agent.get_purchase_request(newer["case_id"])
    merged = combine.merged_items(keep["items"], fold["items"])
    dates = [d for d in (keep.get("needed_by"), fold.get("needed_by")) if d]
    needed_by, urgent = (min(dates) if dates else None), bool(keep.get("urgent") or fold.get("urgent"))

    # the newer request first: suppliers are told it is withdrawn, then it is closed
    approval_agent.withdraw_pending(newer["case_id"])
    vendor_agent.withdraw_rfqs(newer["case_id"], None)
    operations_agent.publish_event(newer["case_id"], combine.MERGED_INTO, agent_name="Operations Agent",
                                   payload={"primary_case_id": older["case_id"], "primary_number": older.get("case_number"), "by": by})
    operations_agent.close_case(newer["case_id"], stage="merged", reason=f"Combined into {older.get('case_number')} by {by}.")

    # the older request carries on with the combined amount
    approval_agent.withdraw_pending(older["case_id"])
    request = purchase_agent.apply_combined(older["case_id"], merged, needed_by, urgent, by, newer.get("case_number"))
    if vendor_agent.get_rfqs(older["case_id"]) and not automation.is_paused():
        rounds = sum(1 for e in operations_agent.get_case_events(older["case_id"]) if e["event_type"] == "sourcing.restarted")
        with operations_agent.working(older["case_id"], "request_quotes"):
            invited = vendor_agent.restart_sourcing(older["case_id"], request["items"], rounds + 2, **_terms(request))
        calling_agent.notify_email_sent(older["case_id"], invited, "rfq")
        if not invited:
            notification_agent.notify_case_stalled(older["case_id"], "The suppliers could not be asked again for the combined quantities.", team="vendor")
    return {"primary_case_id": older["case_id"], "closed_case_id": newer["case_id"], "items": request["items"]}


def track_deliveries() -> dict:
    """One worker tick over every PO awaiting delivery: chase late vendors, and alert a
    human once the vendor has been chased enough with still no delivery."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = {"chased": 0, "escalated": 0}

    for delivery in delivery_agent.get_open_deliveries():
        action = next_delivery_action(
            delivery, now, settings.DELIVERY_CHASE_INTERVAL_HOURS, settings.DELIVERY_MAX_CHASES,
        )
        if action == "chase":
            with operations_agent.working(delivery["case_id"], "chase_delivery"):
                chased = delivery_agent.chase_vendor(delivery)
            if chased:
                counts["chased"] += 1
        elif action == "escalate":
            delivery_agent.mark_escalated(delivery)
            operations_agent.set_stage(delivery["case_id"], "delivery_late")
            notification_agent.notify_case_stalled(
                delivery["case_id"],
                f"{delivery['po_number']} from {delivery['vendor_name']} was due on "
                f"{delivery['expected_delivery_date']:%d %b %Y} and is still not delivered after "
                f"{delivery['chase_count']} follow-up(s). Please contact the vendor.",
                team="delivery",
            )
            counts["escalated"] += 1
    return counts


def confirm_delivery(case_id: str, received_by: str, note: str | None, items: dict[str, int] | None = None) -> dict:
    """A person records goods that arrived (leave `items` out for everything still owed). Once every item is in,
    chasing stops and the case moves on; until then the order stays open and only the rest is chased."""
    try:
        po_before = purchase_order_agent.find_purchase_order(case_id)      # (only for the checks below: if it cannot be read, receiving still goes ahead)
    except Exception:
        logger.exception("Could not read the order before receiving goods on case %s", case_id)
        po_before = None
    try:
        result = delivery_agent.confirm_received(case_id, received_by, note, items)
    except InvalidInput:
        _flag_over_delivery(case_id, po_before, items)         # the receipt is still refused (only what was ordered can be received), but never silently
        raise
    if po_before is not None and not po_before.get("acknowledged_at") and (po_before.get("confirm_chase_count") or po_before.get("confirm_escalated_at")):
        # The supplier never answered our requests to confirm the order, yet the goods came. Logged on the case (normal deliveries are not);
        # the goods are proof enough that they have the order, so nobody needs to act.
        operations_agent.publish_event(case_id, "delivery.before_confirmation", agent_name="Delivery Agent",
                                       payload={"po_number": po_before["po_number"], "received_by": received_by, "chases": po_before.get("confirm_chase_count") or 0})
    _top_up_stock(case_id, result.pop("just_received", {}), received_by)
    _acknowledge_quietly(case_id, via="delivery")        # goods are here, so the supplier plainly has the order
    if result["delivery_status"] != "delivered":
        return result                                    # part delivery: nothing else moves yet
    operations_agent.set_stage(case_id, "delivered")
    _release_held_invoices(case_id)
    _finalise(case_id)
    return result


def _flag_over_delivery(case_id: str, po: dict | None, items: dict[str, int] | None) -> None:
    """A receipt says more arrived than is owed. Only what was ordered can be received, so it is refused, but Receiving and Accounts are told
    (once for the same quantities) so the extra is sorted out with the supplier and never paid for by accident. Never raises."""
    try:
        lines = delivery_agent.over_delivery(case_id, items)
        if not lines or po is None:
            return
        text = agent_cases.over_delivery_text(lines)
        if any(e["event_type"] == "delivery.over_delivered" and (e.get("payload") or {}).get("text") == text for e in operations_agent.get_case_events(case_id)):
            return
        operations_agent.publish_event(case_id, "delivery.over_delivered", agent_name="Delivery Agent", payload={"po_number": po["po_number"], "lines": lines, "text": text})
        msg = (f"More arrived than was ordered on {po['po_number']} from {po['vendor_name']}: {text}. Only the ordered quantity can be received here. "
               f"Please agree with the supplier what happens to the extra (send back, or a new order).")
        notification_agent.notify_case_stalled(case_id, msg, team="delivery")
        notification_agent.notify_case_stalled(case_id, msg + " Do not pay for the extra.", team="invoice")
    except Exception:
        logger.exception("Could not flag the over-delivery on case %s", case_id)


def _top_up_stock(case_id: str, received: dict[str, int], by: str = "Procurement Agent") -> None:
    """Goods ordered to refill the shelf (a low-stock reorder) go into stock as they arrive. Goods bought for a request go to the
    person who asked, so they never touch the stock count. Receiving is already recorded and must not fail because of this: a problem is
    logged and shown on the case instead."""
    if not received:
        return
    try:
        if not any(e["event_type"] == "restock.requested" for e in operations_agent.get_case_events(case_id)):
            return
        result = procurement_agent.receive_into_stock(received, case_id=case_id, actor=by)
        if result["added"]:
            operations_agent.publish_event(case_id, "stock.increased", agent_name="Procurement Agent", payload={"items": result["added"]})
        if result["unmatched"]:
            operations_agent.publish_event(case_id, "stock.topup_unmatched", agent_name="Procurement Agent", payload={"items": result["unmatched"]})
    except Exception:
        logger.exception("Could not add the received goods of case %s to stock", case_id)
        operations_agent.publish_event(case_id, "stock.topup_failed", agent_name="Procurement Agent", payload={"items": received})


def _release_held_invoices(case_id: str) -> None:
    """An invoice that was only waiting for the goods (or for a goods problem to be sorted out) can now clear."""
    if goods_issues.open_issues(delivery_agent.get_issues(case_id)):
        return
    for invoice in invoice_agent.get_invoices(case_id):
        if invoice["status"] == "on_hold":
            invoice_agent.re_evaluate(invoice, "matched", [])


def resume_held_cases() -> dict:
    """Catch up on work that was held by the pause switch, or interrupted (e.g. a restart between
    steps): cases that need quote requests sent or a purchase order raised. Only cases untouched
    for a few minutes are picked up, so this never races a request still being processed."""
    counts = {"rfqs": 0, "purchase_orders": 0}

    for case_id in operations_agent.find_idle_cases("sourcing_needed", settings.HELD_CASE_GRACE_MINUTES):
        _request_quotes(case_id)
        counts["rfqs"] += 1

    for case_id in operations_agent.find_idle_cases("approved", settings.HELD_CASE_GRACE_MINUTES):
        _issue_purchase_order_safely(case_id)
        counts["purchase_orders"] += 1
    return counts


def _issue_purchase_order_safely(case_id: str) -> None:
    """Approval is already recorded and can't be repeated, so a PO failure must not undo
    or hide it: park the case for a human and keep a retry path instead of raising."""
    if automation.is_paused():
        # The case stays at 'approved'; resume_held_cases raises the order once automation resumes.
        operations_agent.publish_event(
            case_id, "automation.held", agent_name="Operations Agent",
            payload={"waiting_for": "purchase order"},
        )
        return
    try:
        issue_purchase_order(case_id)
    except QuoteExpired:
        return                                           # not a failure: the supplier was asked to refresh the price
    except Exception as exc:
        logger.exception("Issuing the purchase order failed for case %s", case_id)
        operations_agent.publish_event(
            case_id, "po.error", agent_name="PO Agent", payload={"error": str(exc)},
        )
        operations_agent.set_stage(case_id, "po_failed")
        notification_agent.notify_case_stalled(
            case_id, f"The purchase order could not be created automatically: {exc}", team="po",
        )


def chase_invoice_corrections() -> dict:
    """One worker tick over rejected invoices still waiting for a corrected one: remind the supplier on schedule, then
    tell Accounts once the reminders have run out, then the admin if even that is ignored."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = {"reminded": 0, "alerted": 0, "escalated": 0}
    rejected = invoice_agent.list_invoices("rejected")
    if not rejected:
        return counts

    open_cases = {c["case_id"].lower() for c in operations_agent.get_all_cases(None) if c["status"] == "open"}
    latest: dict[str, dict] = {}  # the most recently rejected invoice of each open case
    for inv in rejected:
        key = inv["case_id"].lower()
        if key in open_cases and inv.get("decided_at") and (key not in latest or inv["decided_at"] > latest[key]["decided_at"]):
            latest[key] = inv
    vendors = {v["vendor_id"].lower(): v for v in vendor_agent.get_all_vendors()}

    for inv in latest.values():
        if any(other["created_at"] > inv["decided_at"] for other in invoice_agent.get_invoices(inv["case_id"])):
            continue  # a newer invoice arrived: the supplier has answered, that one is being handled
        events = operations_agent.get_case_events(inv["case_id"])
        iid = inv["invoice_id"].lower()
        about = [e for e in events if str((e.get("payload") or {}).get("invoice_id", "")).lower() == iid]
        chases = [e["created_at"] for e in about if e["event_type"] == "invoice.chased" and e["payload"].get("sent")]
        alerted = next((e["created_at"] for e in about if e["event_type"] == "invoice.correction_overdue"), None)
        escalated = any(e["event_type"] == "escalation.sent" and str((e.get("payload") or {}).get("ref", "")).lower() == iid for e in events)
        vendor = vendors.get(inv["vendor_id"].lower()) or {}

        action = next_invoice_chase_action(
            inv["decided_at"], chases, alerted, escalated, now, settings.INVOICE_CHASE_HOURS, settings.INVOICE_MAX_CHASES,
            settings.ESCALATE_AFTER_HOURS, can_email=bool(vendor.get("email")))
        number = inv["invoice_number"] or "(number unreadable)"
        if action == "remind":
            with operations_agent.working(inv["case_id"], "chase_invoice"):
                if invoice_agent.request_corrected_invoice(inv, vendor.get("email"), inv.get("decision_note"), reminder=len(chases) + 1):
                    counts["reminded"] += 1
        elif action == "alert":
            notification_agent.notify_case_stalled(
                inv["case_id"], f"{inv['vendor_name']} has not sent a corrected invoice for {number} ({inv['po_number']}) "
                f"after {len(chases)} reminder(s). Please contact them.", team="invoice")
            operations_agent.publish_event(inv["case_id"], "invoice.correction_overdue", agent_name="Invoice Agent",
                                           payload={"invoice_id": inv["invoice_id"], "reminders": len(chases)})
            counts["alerted"] += 1
        elif action == "escalate":
            hours = round((now - alerted).total_seconds() / 3600, 1)
            notification_agent.notify_escalation(inv["case_id"], "A supplier still has not sent a corrected invoice", hours, f"{inv['po_number']} · {number}")
            operations_agent.publish_event(inv["case_id"], "escalation.sent", agent_name="Notification Agent",
                                           payload={"kind": "invoice_correction", "ref": iid, "hours": hours})
            counts["escalated"] += 1
    return counts


def escalate_overdue() -> int:
    """Tell the admins about anything that has waited too long with nobody acting. Each problem is escalated once
    (remembered on the case), not on every tick. Returns how many were escalated."""
    hours = settings.ESCALATE_AFTER_HOURS
    if hours <= 0:
        return 0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    approvals = approval_agent.get_approvals(status="pending")
    cases = operations_agent.get_all_cases(None)
    invoices = invoice_agent.list_invoices("mismatch")

    urgent_ids = {c["case_id"].lower() for c in cases if c.get("urgent")}
    urgent_hours = min(hours, settings.URGENT_ESCALATE_HOURS)
    candidates = due_escalations(now, hours, approvals, cases, invoices, set(), urgent_ids, urgent_hours)
    if not candidates:
        return 0
    already: set[tuple[str, str]] = set()
    for case_id in {c["case_id"] for c in candidates}:
        for e in operations_agent.get_case_events(case_id):
            if e["event_type"] == "escalation.sent" and e.get("payload"):
                already.add((e["payload"].get("kind", ""), str(e["payload"].get("ref", "")).lower()))

    sent = 0
    for item in due_escalations(now, hours, approvals, cases, invoices, already, urgent_ids, urgent_hours):
        label = " · ".join(x for x in (item["case_number"], item["summary"]) if x) or None
        notification_agent.notify_escalation(item["case_id"], item["what"], item["hours_waiting"], label)
        operations_agent.publish_event(
            item["case_id"], "escalation.sent", agent_name="Notification Agent",
            payload={"kind": item["kind"], "ref": item["ref"], "hours": item["hours_waiting"]},
        )
        sent += 1
    return sent


def check_approver_cover(case_id: str, approval_id: str | None = None) -> bool:
    """Is there anyone who can really decide this approval? If not (nobody has the right, no one has an e-mail address, or the only approver is
    the requester) the admins are told WHY and the case says so, once per approval. True when it was routed to the admins. Never raises."""
    try:
        events = operations_agent.get_case_events(case_id)
        if any(e["event_type"] == "approval.routed_to_admin" and (e.get("payload") or {}).get("approval_id") == approval_id for e in events):
            return True
        requester = operations_agent.get_case_status(case_id).get("requester_id")
        people, directory, today = notification_agent.approver_cover_inputs()
        cover = agent_cases.approver_cover(people, requester, directory, today)
        for d in cover.get("delegations", []):
            if not any(e["event_type"] == "approval.delegated" and (e.get("payload") or {}).get("approval_id") == approval_id
                       and (e.get("payload") or {}).get("from") == d["from"] for e in events):
                operations_agent.publish_event(case_id, "approval.delegated", agent_name="Approval Agent",
                                               payload={"approval_id": approval_id, "from": d["from"], "to": d["to"]})
        if cover["reason"] is None:
            return False
        operations_agent.publish_event(case_id, "approval.routed_to_admin", agent_name="Approval Agent",
                                       payload={"approval_id": approval_id, "reason": cover["reason"]})
        notification_agent.notify_case_stalled(case_id, f"An order needs an approval, but it cannot go to a normal approver: {cover['reason']} "
                                                        f"Please approve it yourself or give someone the approval right.", team=None)
        return True
    except Exception:
        logger.exception("Could not check who can approve on case %s", case_id)
        return False


def handle_user_left(username: str, display: str | None = None, user_id: str | None = None) -> dict:
    """An account was deactivated or deleted. The requests they asked for are still open and nobody follows them, and an approval may have lost
    its only approver: the admins are told (one e-mail) and each request says so on its timeline; pending approvals are re-checked for cover.
    Never raises: the admin's own action must not fail because of this."""
    out = {"cases": 0, "approvals": 0}
    if user_id:
        try:
            approval_link_agent.revoke_user_links(user_id)          # the one-tap e-mail links made for them stop working at once
        except Exception:
            logger.exception("Could not revoke the approval links of %s", username)
    try:
        cases = agent_cases.owned_open_cases(operations_agent.get_all_cases(None), username)
        for c in cases:
            operations_agent.publish_event(c["case_id"], "case.owner_left", agent_name="Operations Agent", payload={"user": username})
        if cases:
            notification_agent.notify_case_stalled(cases[0]["case_id"], agent_cases.left_text(display or username, cases) + "\nPlease decide who follows them up.", team=None)
        out["cases"] = len(cases)
        for approval in approval_agent.get_approvals(status="pending"):
            if check_approver_cover(approval["case_id"], approval["approval_id"]):
                out["approvals"] += 1
    except Exception:
        logger.exception("Could not look after the work of the user who left (%s)", username)
    return out


def sweep_stuck_cases() -> int:
    """The general "stuck too long" check (core/stuck_policy.py). A case quiet at one stage past its limit: the case says so and the right
    department is emailed, once; still quiet a while later: the admin is emailed, once. Moving the case on starts it afresh. Returns how
    many notices went out."""
    hours = stuck_policy.limits(settings.STUCK_AUTOMATIC_HOURS, settings.STUCK_PERSON_HOURS, settings.STUCK_WAITING_HOURS)
    if not any(h > 0 for h in hours.values()):
        return 0
    now = _now()
    cases = operations_agent.get_all_cases(None)
    updated = {c["case_id"]: c["updated_at"] for c in cases}
    sent = attempts = 0
    for item in stuck_policy.candidates(now, cases, hours):
        case_id = item["case_id"]
        done = stuck_policy.already_done(operations_agent.get_case_events(case_id), updated[case_id])
        step = stuck_policy.next_step(item, done, settings.STUCK_ESCALATE_AFTER_HOURS)
        if step is None:
            continue
        if attempts >= max(settings.STUCK_MAX_PER_TICK, 1):
            break                       # the rest follow on later passes (oldest first), so a first run over many old cases cannot flood anyone
        attempts += 1
        label = " · ".join(x for x in (item["case_number"], item["summary"]) if x) or case_id
        what = f"has sat at '{item['stage'].replace('_', ' ')}' for about {item['quiet_hours']:g} hours with nothing moving"
        try:
            if step == "notify":
                notification_agent.notify_case_stalled(case_id, f"{label} {what}. Please look at it.", team=item["team"])
                operations_agent.publish_event(case_id, stuck_policy.STUCK_EVENT, agent_name="Operations Agent",
                                               payload={"stage": item["stage"], "hours": item["quiet_hours"], "team": item["team"]})
            else:
                notification_agent.notify_escalation(case_id, f"{label} {what}", item["quiet_hours"], label)
                operations_agent.publish_event(case_id, stuck_policy.ESCALATED_EVENT, agent_name="Operations Agent",
                                               payload={"stage": item["stage"], "hours": item["quiet_hours"]})
            sent += 1
        except Exception:
            logger.exception("Could not report the stuck case %s", case_id)          # one bad case must not stop the sweep
    return sent


def reroute_pending_approvals(limit: int = 20) -> dict:
    """Someone's leave (or their backup) was changed: every approval still waiting is checked for cover again, and sent again to whoever is
    asked NOW (the delegate of someone who just went on leave, say). Never raises: the admin's own edit must not fail because of this."""
    out = {"renotified": 0, "to_admin": 0}
    try:
        for approval in approval_agent.get_approvals(status="pending")[:limit]:
            if check_approver_cover(approval["case_id"], approval.get("approval_id")):
                out["to_admin"] += 1
            if approval.get("approval_type") not in (None, "vendor_selection"):
                continue
            selection = vendor_agent.get_vendor_selection(approval["case_id"])
            notification_agent.notify_approval_needed(
                approval["case_id"], selection["vendor_name"], selection["rationale"], approval["reasons"], reminder=True,
                **_one_tap_context(approval), **_email_review(approval))
            approval_agent.mark_reminded(approval["approval_id"])
            out["renotified"] += 1
    except Exception:
        logger.exception("Could not send the waiting approvals again after a leave change")
    return out


def remind_pending_approvals() -> int:
    """Re-notify managers about approvals nobody has answered. Returns how many were re-sent."""
    now = _now()
    normal_hours = settings.APPROVAL_REMINDER_HOURS
    quickest = min(normal_hours, settings.URGENT_APPROVAL_REMINDER_HOURS)
    due = approval_agent.get_approvals_needing_reminder(now - timedelta(hours=quickest), settings.APPROVAL_MAX_REMINDERS)
    if not due:
        return 0
    urgent_ids = {c["case_id"].lower() for c in operations_agent.get_all_cases(None) if c.get("urgent")}
    sent = 0
    for approval in due:
        if approval["case_id"].lower() not in urgent_ids:       # an ordinary request waits the usual time
            touched = approval.get("last_reminded_at") or approval["created_at"]
            if now - touched < timedelta(hours=normal_hours):
                continue
        selection = vendor_agent.get_vendor_selection(approval["case_id"])
        notification_agent.notify_approval_needed(
            approval["case_id"], selection["vendor_name"], selection["rationale"],
            approval["reasons"], reminder=True, **_one_tap_context(approval), **_email_review(approval),
        )
        approval_agent.mark_reminded(approval["approval_id"])
        sent += 1
    return sent
