import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.agents import operations_agent
from app.clients import azure_openai_client, email_client
from app.core.config import settings
from app.core import negotiation, preferred, quote_expiry
from app.core import quotes as quote_rules
from app.core import urgency
from app.core.email_parsing import make_subject
from app.core.exceptions import InvalidInput, NoQuotesFound, RuleViolation, VendorNotFound, VendorSelectionNotFound
from app.core.vendor_ranking import normalize_ranking
from app.repositories import rfq_repository, vendor_repository

logger = logging.getLogger(__name__)

QUOTE_EXTRACTION_PROMPT = (
    "You are the Vendor Agent in a procurement system. Read the raw vendor quote "
    "text and extract structured fields. Respond ONLY with a JSON object with "
    "exactly these keys: price (number or null if not mentioned -- use the total "
    "price, not a per-unit price, if both are mentioned), lead_time_days (integer "
    "or null), terms (string or null, e.g. payment terms or warranty), valid_days (integer "
    "number of days the price stays valid, only if the vendor states it, e.g. \"valid for 7 days\"; otherwise null)."
)

RANKING_PROMPT = (
    "You are the Vendor Agent in a procurement system. You are given a list of "
    "vendor quotes for the same purchase request, each with the vendor's id, name, "
    "price, lead time, terms, and a reliability score (1-5, higher is better based "
    "on past performance). Rank ALL the vendors from best to worst, weighing price, "
    "delivery speed, terms, and reliability together. Respond ONLY with a JSON object "
    "with exactly these keys: ranking (a list with one object per vendor, best first, "
    "each with vendor_id (must exactly match a given id) and reason (one short sentence "
    "naming the trade-off, e.g. cheapest but slowest, or dearer but quicker with "
    "better terms)), recommended_vendor_id (the first vendor in the ranking), "
    "rationale (one or two sentences on why the first is best overall)."
)


def get_all_vendors() -> list[dict]:
    rows = vendor_repository.find_all_vendors()
    return [
        {
            "vendor_id": str(row.vendor_id),
            "name": row.name,
            "email": row.email,
            "phone": getattr(row, "phone", None),
            "call_language": getattr(row, "call_language", None) or "hi",
            "reliability_score": float(row.reliability_score),
            "created_at": row.created_at,
            "email_bounced_at": getattr(row, "email_bounced_at", None),
            "email_bounce_reason": getattr(row, "email_bounce_reason", None),
        }
        for row in rows
    ]


def find_vendor_by_email(address: str) -> dict | None:
    row = vendor_repository.find_vendor_by_email(address)
    return {"vendor_id": str(row.vendor_id), "name": row.name, "email": row.email} if row else None


def mark_email_bounced(vendor_id: str, reason: str) -> None:
    vendor_repository.mark_email_bounced(vendor_id, reason)


def mark_rfq_bounced(case_id: str, vendor_id: str) -> None:
    rfq_repository.mark_bounced(case_id, vendor_id)


def open_case_ids_for_vendor(vendor_id: str) -> list[str]:
    return rfq_repository.find_open_case_ids_for_vendor(vendor_id)


def upsert_vendor(name: str, reliability_score: float, email: str | None = None,
                  phone: str | None = None, call_language: str | None = None) -> None:
    vendor_repository.upsert_vendor(name, reliability_score, email, phone, call_language)


def update_vendor(vendor_id: str, name: str, email: str | None, phone: str | None, call_language: str, reliability_score: float) -> dict:
    """Change a supplier's details. The name and the e-mail address must not belong to another supplier (replies are matched to a
    supplier by the address they come from). Returns the details as they were before, so the caller can record what changed."""
    vendors = get_all_vendors()
    current = next((v for v in vendors if v["vendor_id"].lower() == vendor_id.strip().lower()), None)
    if current is None:
        raise VendorNotFound(vendor_id)
    for other in vendors:
        if other["vendor_id"] == current["vendor_id"]:
            continue
        if other["name"].strip().lower() == name.strip().lower():
            raise InvalidInput(f"There is already a supplier called '{other['name']}'.")
        if email and (other["email"] or "").strip().lower() == email.strip().lower():
            raise InvalidInput(f"{other['name']} already uses that e-mail address, so replies could not be told apart.")
    vendor_repository.update_vendor(current["vendor_id"], name.strip(), email.strip() if email else None, phone, call_language, reliability_score)
    return current


def send_rfqs(case_id: str, items: list[dict], deadline_hours: float | None = None, note: str = "",
              preferred_vendor_ids: list[str] | None = None) -> list[str]:
    """Email every vendor that has an address asking for a quote on `items`, and start the
    clock. Returns the names invited. If nobody could be reached, the case is flagged for a human.
    `deadline_hours` and `note` are shorter / stronger for an urgent request (see core/urgency.py)."""
    deadline = _utcnow() + timedelta(hours=deadline_hours or settings.RFQ_DEADLINE_HOURS)

    invited, failed, skipped = [], [], []
    vendors = get_all_vendors()
    _warn_preferred_unreachable(case_id, vendors, preferred_vendor_ids)
    vendors = preferred.order_for_asking(vendors, preferred_vendor_ids)      # preferred suppliers are asked first; nobody is added or dropped
    reachable = sum(1 for v in vendors if v["email"] and not v.get("email_bounced_at"))
    for vendor in vendors:
        if not vendor["email"] or vendor.get("email_bounced_at"):          # no address, or one that is known not to work
            skipped.append(vendor["name"])
            continue
        try:
            email_client.send_email(
                vendor["email"], _rfq_subject(case_id, bool(note)),
                _rfq_body(vendor["name"], items, deadline, reminder=False, note=note),
            )
        except Exception:
            logger.exception("RFQ email to %s failed for case %s", vendor["name"], case_id)
            failed.append(vendor["name"])
            continue
        rfq_repository.insert_rfq(str(uuid.uuid4()), case_id, vendor["vendor_id"], deadline)
        invited.append(vendor["name"])
        operations_agent.report_progress(len(invited), reachable, f"Asked {len(invited)} of {reachable} suppliers")

    if not invited:
        operations_agent.publish_event(
            case_id, "sourcing.no_vendors", agent_name="Vendor Agent",
            payload={"failed": failed, "skipped_no_email": skipped},
        )
        operations_agent.set_stage(case_id, "sourcing_stalled")
        return []

    operations_agent.publish_event(
        case_id, "rfq.sent", agent_name="Vendor Agent",
        payload={"vendors": invited, "failed": failed, "skipped_no_email": skipped,
                 "deadline_at": deadline.isoformat()},
    )
    operations_agent.set_stage(case_id, "awaiting_quotes")
    return invited


def _warn_preferred_unreachable(case_id: str, vendors: list[dict], preferred_vendor_ids, skip_vendor_id: str | None = None) -> None:
    """A preferred supplier who cannot be asked is shown on the case, so the request does not quietly go out without them."""
    names = preferred.unreachable_preferred(vendors, preferred_vendor_ids, skip_vendor_id)
    if names:
        operations_agent.publish_event(case_id, "rfq.preferred_unreachable", agent_name="Vendor Agent", payload={"vendors": names})


def restart_sourcing(case_id: str, items: list[dict], round_no: int, skip_vendor_id: str | None = None,
                     deadline_hours: float | None = None, note: str = "", preferred_vendor_ids: list[str] | None = None) -> list[str]:
    """Ask for new quotes after the offers were turned down. The earlier quotes stay on record but stop counting, the
    chosen supplier is cleared, and every supplier with an email (except `skip_vendor_id`, who is not asked again)
    gets a fresh request and a fresh clock. Returns who was asked; if nobody could be reached the case is stalled."""
    quotes_before = get_quotes(case_id)
    vendor_repository.supersede_quotes(case_id)
    vendor_repository.delete_vendor_selection(case_id)

    deadline = _utcnow() + timedelta(hours=deadline_hours or settings.RFQ_DEADLINE_HOURS)
    existing = {str(r.vendor_id).lower(): r for r in rfq_repository.find_rfqs_by_case_id(case_id)}
    skip = (skip_vendor_id or "").lower()

    invited, failed, skipped = [], [], []
    vendors = get_all_vendors()
    _warn_preferred_unreachable(case_id, vendors, preferred_vendor_ids, skip_vendor_id)
    vendors = preferred.order_for_asking(vendors, preferred_vendor_ids)
    reachable = sum(1 for v in vendors if v["email"] and not v.get("email_bounced_at") and v["vendor_id"].lower() != skip)
    for vendor in vendors:
        vid = vendor["vendor_id"].lower()
        if vid == skip:
            if vid in existing:
                rfq_repository.delete_rfq(case_id, vendor["vendor_id"])   # not asked again, so nobody waits on them
            continue
        if not vendor["email"] or vendor.get("email_bounced_at"):
            skipped.append(vendor["name"])
            continue
        try:
            email_client.send_email(vendor["email"], _rfq_subject(case_id, bool(note)), _rfq_body(vendor["name"], items, deadline, reminder=False, revised=True, note=note))
        except Exception:
            logger.exception("Revised RFQ email to %s failed for case %s", vendor["name"], case_id)
            failed.append(vendor["name"])
            if vid in existing:
                rfq_repository.delete_rfq(case_id, vendor["vendor_id"])
            continue
        if vid in existing:
            rfq_repository.reopen(str(existing[vid].rfq_id), deadline)
        else:
            rfq_repository.insert_rfq(str(uuid.uuid4()), case_id, vendor["vendor_id"], deadline)
        invited.append(vendor["name"])
        operations_agent.report_progress(len(invited), reachable, f"Asked {len(invited)} of {reachable} suppliers again")

    operations_agent.publish_event(
        case_id, "sourcing.restarted", agent_name="Vendor Agent",
        payload={"round": round_no, "vendors": invited, "failed": failed, "skipped_no_email": skipped,
                 "dropped_quotes": len(quotes_before), "deadline_at": deadline.isoformat(), "skipped_vendor_id": skip_vendor_id},
    )
    if not invited:
        operations_agent.set_stage(case_id, "sourcing_stalled")
        return []
    operations_agent.set_stage(case_id, "awaiting_quotes")
    return invited


def request_quote_refresh(case_id: str, vendor_id: str, items: list[dict], expired_on, deadline_hours: float | None = None, note: str = "",
                          preferred_vendor_ids: list[str] | None = None) -> bool:
    """A supplier's quote ran out before the order could be placed: ask them to confirm or update it. Their old quote stops
    counting (it stays on record), the choice is cleared, and their request is reopened with a fresh deadline.
    Returns whether the email went out."""
    vendor = next((v for v in get_all_vendors() if v["vendor_id"].lower() == vendor_id.lower()), None)
    vendor_repository.supersede_vendor_quotes(case_id, vendor_id)
    vendor_repository.delete_vendor_selection(case_id)
    deadline = _utcnow() + timedelta(hours=deadline_hours or settings.RFQ_DEADLINE_HOURS)
    existing = next((r for r in rfq_repository.find_rfqs_by_case_id(case_id) if str(r.vendor_id).lower() == vendor_id.lower()), None)
    if existing:
        rfq_repository.reopen(str(existing.rfq_id), deadline)
    else:
        rfq_repository.insert_rfq(str(uuid.uuid4()), case_id, vendor_id, deadline)
    sent = False
    if vendor and vendor["email"]:
        lines = "\n".join(f"  - {i['description']} x {i['quantity']}" for i in items)
        body = (f"Dear {vendor['name']},\n\nYour quotation for the items below expired on {expired_on:%d %b %Y}:\n\n{lines}\n\n"
                f"{note + chr(10) + chr(10) if note else ''}"
                f"Please reply to confirm that your price and delivery time still hold, or send an updated quotation, by {deadline:%d %b %Y %H:%M} UTC.\n\nThank you.")
        try:
            email_client.send_email(vendor["email"], _rfq_subject(case_id, bool(note)).replace("Request for quotation", "Quotation expired - please refresh"), body)
            sent = True
        except Exception:
            logger.exception("Quote refresh email to %s failed for case %s", vendor["name"], case_id)
    operations_agent.publish_event(
        case_id, "quote.refresh_requested", agent_name="Vendor Agent",
        payload={"vendor_id": vendor_id, "vendor": vendor["name"] if vendor else None, "expired_on": expired_on.isoformat(), "emailed": sent},
    )
    operations_agent.set_stage(case_id, "awaiting_quotes")
    return sent


def withdraw_rfqs(case_id: str, reason: str | None = None) -> list[str]:
    """Tell every supplier who was asked for a price that the request is withdrawn, and stop waiting on them.
    Returns the names told. A supplier that cannot be emailed is simply not told (a person can ring them)."""
    told, failed = [], []
    for rfq in rfq_repository.find_rfqs_by_case_id(case_id):
        if rfq.status == "withdrawn" or not rfq.vendor_email:
            continue
        body = (f"Dear {rfq.vendor_name},\n\nWe no longer need the quotation we asked for. Please disregard our earlier request"
                f"{' (' + reason + ')' if reason else ''}. You do not need to reply.\n\nThank you for your time.")
        try:
            email_client.send_email(rfq.vendor_email, _rfq_subject(case_id).replace("Request for quotation", "Request for quotation - WITHDRAWN"), body)
            told.append(rfq.vendor_name)
        except Exception:
            logger.exception("Withdrawal email to %s failed for case %s", rfq.vendor_name, case_id)
            failed.append(rfq.vendor_name)
    rfq_repository.mark_withdrawn(case_id)
    if told or failed:
        operations_agent.publish_event(case_id, "rfq.withdrawn", agent_name="Vendor Agent", payload={"vendors": told, "failed": failed})
    return told


def send_reminders(case_id: str, items: list[dict], rfq_ids: list[str]) -> None:
    due = set(rfq_ids)
    reminded = []
    for rfq in rfq_repository.find_rfqs_by_case_id(case_id):
        if str(rfq.rfq_id) not in due:
            continue
        try:
            email_client.send_email(
                rfq.vendor_email, _rfq_subject(case_id),
                _rfq_body(rfq.vendor_name, items, rfq.deadline_at, reminder=True),
            )
        except Exception:
            logger.exception("Reminder to %s failed for case %s", rfq.vendor_name, case_id)
            continue
        rfq_repository.mark_reminded(str(rfq.rfq_id))
        reminded.append(rfq.vendor_name)
        operations_agent.report_progress(len(reminded), len(due), f"Reminded {len(reminded)} of {len(due)} suppliers")

    if reminded:
        operations_agent.publish_event(
            case_id, "rfq.reminded", agent_name="Vendor Agent", payload={"vendors": reminded},
        )


def get_rfqs(case_id: str) -> list[dict]:
    return [_row_to_rfq_dict(r) for r in rfq_repository.find_rfqs_by_case_id(case_id)]


def read_quote(raw_quote_text: str, images: list[str] | None = None) -> dict:
    """What a supplier's text says (price, lead time, terms, validity) WITHOUT recording a quote: for deciding whether it is worth recording."""
    return (azure_openai_client.ask_json(QUOTE_EXTRACTION_PROMPT, raw_quote_text, images=images) if images
            else azure_openai_client.ask_json(QUOTE_EXTRACTION_PROMPT, raw_quote_text))


def ask_better_price(case_id: str, vendor_id: str, items: list[dict], price: float, wait_hours: float) -> bool:
    """E-mail the chosen supplier once, asking for a better price. The case tag is in the subject so their reply lands on this case.
    False (nothing sent) when there is no address or sending failed."""
    vendor = next((v for v in get_all_vendors() if v["vendor_id"].lower() == vendor_id.lower()), None)
    if not vendor or not vendor["email"]:
        return False
    try:
        email_client.send_email(vendor["email"], _rfq_subject(case_id).replace("Request for quotation", "Can you improve your price?"),
                                negotiation.message(vendor["name"], items, price, wait_hours))
    except Exception:
        logger.exception("Could not ask %s for a better price on case %s", vendor["name"], case_id)
        return False
    return True


def submit_quote(case_id: str, vendor_id: str, raw_quote_text: str, images: list[str] | None = None, structured: dict | None = None) -> dict:
    which = None
    if operations_agent.step_active():  # only worth counting when someone is watching the step
        which = (len(vendor_repository.find_quotes_by_case_id(case_id)) + 1, max(1, len(rfq_repository.find_rfqs_by_case_id(case_id))))
        operations_agent.report_progress(1, 3, f"Reading quote {which[0]} of {which[1]}")
    if structured is None:
        structured = (azure_openai_client.ask_json(QUOTE_EXTRACTION_PROMPT, raw_quote_text, images=images) if images
                      else azure_openai_client.ask_json(QUOTE_EXTRACTION_PROMPT, raw_quote_text))
    if which:
        operations_agent.report_progress(2, 3, f"Understood the price and delivery time of quote {which[0]}")

    quote_id = str(uuid.uuid4())
    vendor_repository.insert_quote(
        quote_id=quote_id,
        case_id=case_id,
        vendor_id=vendor_id,
        raw_quote_text=raw_quote_text,
        price=structured.get("price"),
        lead_time_days=structured.get("lead_time_days"),
        terms=structured.get("terms"),
        valid_until=quote_expiry.valid_until(_utcnow(), structured.get("valid_days")),
    )
    rfq_repository.mark_replied(case_id, vendor_id)

    operations_agent.publish_event(
        case_id, "quote.submitted", agent_name="Vendor Agent",
        payload={"vendor_id": vendor_id, **structured},
    )

    return _find_quote(case_id, quote_id)


def get_quotes(case_id: str, include_superseded: bool = False) -> list[dict]:
    rows = vendor_repository.find_quotes_by_case_id(case_id, include_superseded) if include_superseded else vendor_repository.find_quotes_by_case_id(case_id)
    return [_row_to_quote_dict(row) for row in rows]


def list_all_quotes() -> list[dict]:
    return [{"quote_id": str(r.quote_id), "case_id": str(r.case_id), "vendor_id": str(r.vendor_id), "vendor_name": r.vendor_name,
             "price": float(r.price) if r.price is not None else None, "created_at": r.created_at} for r in vendor_repository.find_all_quotes()]


def get_earlier_quotes(case_id: str) -> list[dict]:
    """Quotes from an earlier round that was turned down (kept for the record, no longer counted)."""
    return [q for q in get_quotes(case_id, include_superseded=True) if q.get("superseded_at")]


def rank_vendors(case_id: str, needed_by=None) -> dict:
    """`needed_by` (the date the goods are needed) is handed in by the pipeline; each vendor is then marked as meeting it or not."""
    quotes = quote_rules.latest_per_vendor(get_quotes(case_id))     # a supplier who quoted twice is judged on the latest price
    if not quotes:
        raise NoQuotesFound(case_id)

    vendors_by_id = {v["vendor_id"]: v for v in get_all_vendors()}
    today = _utcnow().date()
    quote_summaries = [
        {
            "vendor_id": q["vendor_id"],
            "vendor_name": q["vendor_name"],
            "price": q["price"],
            "lead_time_days": q["lead_time_days"],
            "terms": q["terms"],
            "reliability_score": vendors_by_id.get(q["vendor_id"], {}).get("reliability_score"),
            **({"meets_needed_by": urgency.meets(q["lead_time_days"], needed_by, today)} if needed_by else {}),
        }
        for q in quotes
    ]

    operations_agent.report_progress(1, 3, f"Comparing {len(quotes)} quote{'s' if len(quotes) != 1 else ''} side by side")
    result = azure_openai_client.ask_json(
        RANKING_PROMPT + urgency.ranking_note(needed_by, today), f"Quotes: {quote_summaries}"
    )
    operations_agent.report_progress(2, 3, "Ranking the suppliers and writing the reasons")
    ranking, rationale = normalize_ranking(result, quotes)
    recommended_vendor_id = ranking[0]["vendor_id"]

    vendor_repository.upsert_vendor_selection(case_id, recommended_vendor_id, rationale)
    operations_agent.report_progress(3, 3, "Recommendation ready")

    operations_agent.publish_event(
        case_id, "vendor.selected", agent_name="Vendor Agent",
        payload={"vendor_id": recommended_vendor_id, "rationale": rationale, "ranking": ranking},
    )
    operations_agent.set_stage(case_id, "vendor_selected")

    return get_vendor_selection(case_id)


def choose_vendor(case_id: str, vendor_id: str, chosen_by: str, note: str | None) -> dict | None:
    """A person picks the supplier (instead of the AI's pick). Returns None if it is the supplier already selected,
    otherwise {"from": previous name, "to": new name}. Only a supplier that sent a priced quote on this case can be chosen."""
    quotes = [q for q in get_quotes(case_id) if q["vendor_id"].lower() == vendor_id.lower() and q["price"] is not None]
    if not quotes:
        raise RuleViolation("That supplier has not sent a priced quote for this request, so it can't be chosen.")
    current = get_vendor_selection(case_id)
    if current["vendor_id"].lower() == vendor_id.lower():
        return None
    why = f"Chosen by {chosen_by} instead of {current['vendor_name']}" + (f": {note.strip()}" if note and note.strip() else ".")
    vendor_repository.upsert_vendor_selection(case_id, quotes[0]["vendor_id"], why)
    operations_agent.publish_event(
        case_id, "vendor.selected", agent_name="Vendor Agent",
        payload={"vendor_id": quotes[0]["vendor_id"], "rationale": why, "chosen_by": chosen_by, "replaces": current["vendor_id"]},
    )
    return {"from": current["vendor_name"], "to": quotes[0]["vendor_name"]}


def get_vendor_selection(case_id: str) -> dict:
    row = vendor_repository.find_vendor_selection_by_case_id(case_id)
    if row is None:
        raise VendorSelectionNotFound(case_id)
    return {
        "case_id": str(row.case_id),
        "vendor_id": str(row.vendor_id),
        "vendor_name": row.vendor_name,
        "rationale": row.rationale,
        "created_at": row.created_at,
    }


def _utcnow() -> datetime:
    # SQL Server columns are naive UTC (SYSUTCDATETIME), so keep Python times naive UTC too.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rfq_subject(case_id: str, urgent: bool = False) -> str:
    # The tag lets the mailbox reader match a reply (which keeps the subject) to its case.
    return make_subject(case_id, "URGENT - Request for quotation" if urgent else "Request for quotation")


def mark_declined(case_id: str, vendor_id: str) -> None:
    """The supplier said they cannot supply: that is an answer, so we stop waiting on them (no quote is recorded)."""
    rfq_repository.mark_replied(case_id, vendor_id)


def ask_for_price(case_id: str, vendor_id: str) -> bool:
    """The supplier replied without a price: ask them for one. False (nothing sent) if there is no address or sending failed."""
    vendor = next((v for v in get_all_vendors() if v["vendor_id"].lower() == vendor_id.lower()), None)
    if not vendor or not vendor["email"]:
        return False
    body = (f"Dear {vendor['name']},\n\nThank you for your reply. It did not include a price, so we cannot compare it yet.\n\n"
            f"Please reply with your total price, delivery time (days) and payment terms for the items in our request, "
            f"or tell us if you are not able to supply.\n\nThank you.")
    try:
        email_client.send_email(vendor["email"], _rfq_subject(case_id).replace("Request for quotation", "Your price is needed"), body)
    except Exception:
        logger.exception("Could not ask %s for a price on case %s", vendor["name"], case_id)
        return False
    return True


def find_invited_vendor_id(case_id: str, email: str) -> str | None:
    return rfq_repository.find_vendor_id_by_email(case_id, email)


def _rfq_body(vendor_name: str, items: list[dict], deadline: datetime, reminder: bool, revised: bool = False, note: str = "") -> str:
    lines = "\n".join(f"  - {i['description']} x {i['quantity']}" for i in items)
    intro = ("Reminder: we have not yet received your quotation for the items below." if reminder
             else "We are asking for fresh quotations for the items below. Please send your best current price, even if you quoted before." if revised
             else "Please send us your quotation for the items below.")
    return (
        f"Dear {vendor_name},\n\n{intro}\n\n{lines}\n\n{note + chr(10) + chr(10) if note else ''}"
        f"Please reply with your total price, delivery time (days) and payment/warranty "
        f"terms by {deadline:%d %b %Y %H:%M} UTC.\n\nThank you."
    )


def _row_to_rfq_dict(row) -> dict:
    return {
        "rfq_id": str(row.rfq_id),
        "case_id": str(row.case_id),
        "vendor_id": str(row.vendor_id),
        "vendor_name": row.vendor_name,
        "status": row.status,
        "sent_at": row.sent_at,
        "last_contacted_at": row.last_contacted_at,
        "reminder_count": row.reminder_count,
        "deadline_at": row.deadline_at,
        "replied_at": row.replied_at,
    }


def _find_quote(case_id: str, quote_id: str) -> dict:
    for row in vendor_repository.find_quotes_by_case_id(case_id):
        if str(row.quote_id).lower() == quote_id.lower():
            return _row_to_quote_dict(row)
    raise NoQuotesFound(case_id)


def _row_to_quote_dict(row) -> dict:
    return {
        "quote_id": str(row.quote_id),
        "case_id": str(row.case_id),
        "vendor_id": str(row.vendor_id),
        "vendor_name": row.vendor_name,
        "raw_quote_text": row.raw_quote_text,
        "price": float(row.price) if row.price is not None else None,
        "lead_time_days": row.lead_time_days,
        "terms": row.terms,
        "created_at": row.created_at,
        "superseded_at": getattr(row, "superseded_at", None),
        "valid_until": getattr(row, "valid_until", None),
    }
