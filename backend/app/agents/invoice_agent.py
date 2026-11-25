import json
import logging
import uuid

from app.agents import operations_agent
from app.clients import azure_openai_client, email_client
from app.core.email_parsing import make_subject
from app.core.exceptions import InvoiceAlreadyDecided, InvoiceNotFound
from app.repositories import invoice_repository

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = (
    "You are the Invoice Agent in a procurement system. You are given the text of an email or "
    "document from a vendor. Decide whether it is an INVOICE (a bill asking for payment), and if "
    "so extract its fields. A purchase-order confirmation, a delivery update or a general reply "
    "is NOT an invoice. Respond ONLY with a JSON object with exactly these keys: "
    "is_invoice (boolean), invoice_number (string or null), total_amount (number or null -- the "
    "final total payable including tax, not a per-unit price), po_number (string or null -- the "
    "purchase order number the invoice refers to, like PO-1001), items (array of objects with "
    "'description' (string) and 'quantity' (integer); empty array if the invoice lists no items), "
    "subtotal (number or null -- the amount before tax, only if the invoice states it), tax_rate_pct (number or null -- "
    "the tax / GST rate in percent, only if stated, e.g. 18), tax_amount (number or null -- the tax charged, only if stated)."
)

_MAX_TEXT = 8000


def extract(raw_text: str, images: list[str] | None = None) -> dict:
    """Ask the AI to classify and read an invoice (`images` are page pictures of a scanned one). Anything unreadable comes back
    as None rather than a guess, so the matching policy flags it for a person."""
    if images:
        data = azure_openai_client.ask_json(EXTRACTION_PROMPT, raw_text[:_MAX_TEXT], images=images)
    else:
        data = azure_openai_client.ask_json(EXTRACTION_PROMPT, raw_text[:_MAX_TEXT])
    return {
        "is_invoice": data.get("is_invoice") is True,
        "invoice_number": _clean_text(data.get("invoice_number")),
        "total_amount": _number(data.get("total_amount")),
        "po_number": _clean_text(data.get("po_number")),
        "items": _items(data.get("items")),
        "subtotal": _number(data.get("subtotal")),
        "tax_rate_pct": _number(data.get("tax_rate_pct")),
        "tax_amount": _number(data.get("tax_amount")),
    }


def number_exists(vendor_id: str, invoice_number: str | None) -> bool:
    return bool(invoice_number) and invoice_repository.number_exists(vendor_id, invoice_number)


def record(case_id: str, po: dict, raw_text: str, extracted: dict, status: str,
           issues: list[str], source: str) -> dict:
    invoice_id = str(uuid.uuid4())
    invoice_repository.insert_invoice(
        invoice_id, case_id, po["purchase_order_id"], po["vendor_id"],
        extracted["invoice_number"], extracted["total_amount"], raw_text, extracted,
        status, issues, source,
        tax={"subtotal": extracted.get("subtotal"), "tax_rate_pct": extracted.get("tax_rate_pct"), "tax_amount": extracted.get("tax_amount")},
    )
    operations_agent.publish_event(
        case_id, f"invoice.{status}", agent_name="Invoice Agent",
        payload={"invoice_id": invoice_id, "invoice_number": extracted["invoice_number"],
                 "total_amount": extracted["total_amount"], "issues": issues, "source": source},
    )
    return get_invoice(invoice_id)


def re_evaluate(invoice: dict, status: str, issues: list[str]) -> None:
    invoice_repository.update_evaluation(invoice["invoice_id"], status, issues)
    operations_agent.publish_event(
        invoice["case_id"], f"invoice.{status}", agent_name="Invoice Agent",
        payload={"invoice_id": invoice["invoice_id"], "invoice_number": invoice["invoice_number"],
                 "issues": issues, "re_evaluated": True},
    )


def decide(invoice_id: str, approve: bool, decided_by: str, note: str | None) -> dict:
    invoice = get_invoice(invoice_id)  # raises InvoiceNotFound
    status = "approved" if approve else "rejected"
    if not invoice_repository.decide_open(invoice_id, status, decided_by, note):
        raise InvoiceAlreadyDecided(invoice_id)
    operations_agent.publish_event(
        invoice["case_id"], f"invoice.{status}", agent_name="Invoice Agent",
        payload={"invoice_id": invoice_id, "decided_by": decided_by, "note": note},
    )
    return get_invoice(invoice_id)


def _email_supplier(case_id: str, vendor_email: str | None, subject: str, body: str, event: str, vendor_name: str) -> bool:
    """One email to the supplier, with the case reference in the subject so their reply lands on the same case. Never raises: the
    outcome (sent or not, and why) is recorded on the case either way."""
    sent = False
    if vendor_email:
        try:
            email_client.send_email(vendor_email, make_subject(case_id, subject), body)
            sent = True
        except Exception:
            logger.exception("Could not email %s about case %s", vendor_email, case_id)
    operations_agent.publish_event(
        case_id, event, agent_name="Invoice Agent",
        payload={"vendor": vendor_name, "sent": sent, "reason": None if sent else ("The supplier has no email address." if not vendor_email else "The email could not be sent.")},
    )
    return sent


def ask_to_resend(case_id: str, vendor_email: str | None, vendor_name: str) -> bool:
    """The supplier's document could not be read (a blurry scan, a locked file): ask for one we can."""
    body = (
        f"Dear {vendor_name},\n\nWe received your email but could not read the attached document.\n\n"
        "Please reply to this email with either:\n"
        "  - a PDF that has selectable text (saved or exported from your billing software, not a photo of paper), or\n"
        "  - the details typed in the email: your invoice number, our purchase order number, the items with quantities, and the total.\n\n"
        "Thank you."
    )
    return _email_supplier(case_id, vendor_email, "We could not read your document: please resend it", body, "document.resend_requested", vendor_name)


def ask_for_invoice_details(case_id: str, vendor_email: str | None, vendor_name: str, po_number: str | None) -> bool:
    """The goods are in and the supplier wrote about money, but it was not an invoice (no invoice number, say): ask for the details."""
    order = f" for order {po_number}" if po_number else ""
    body = (
        f"Dear {vendor_name},\n\nThank you for your message. We could not treat it as an invoice{order}.\n\n"
        "To pay you we need an invoice that shows:\n"
        "  - the invoice number,\n"
        f"  - our purchase order number{f' ({po_number})' if po_number else ''},\n"
        "  - the items and quantities,\n"
        "  - the total payable.\n\n"
        "Please reply to this email with those details typed in, or attach the invoice PDF.\n\nThank you."
    )
    return _email_supplier(case_id, vendor_email, "Invoice details needed", body, "invoice.details_requested", vendor_name)


def ask_for_final_invoice(case_id: str, vendor_email: str | None, vendor_name: str, po_number: str | None) -> bool:
    """The supplier sent a proforma invoice: it is not a bill, so ask for the final invoice."""
    order = f" for order {po_number}" if po_number else ""
    body = (
        f"Dear {vendor_name},\n\nThank you for the proforma invoice{order}. We cannot pay against a proforma.\n\n"
        "Please send the final tax invoice (with its invoice number) once the goods have been delivered, quoting "
        f"our purchase order number{f' {po_number}' if po_number else ''}.\n\nThank you."
    )
    return _email_supplier(case_id, vendor_email, "Final invoice needed (proforma received)", body, "invoice.final_requested", vendor_name)


def request_corrected_invoice(invoice: dict, vendor_email: str | None, decided_note: str | None, reminder: int = 0) -> bool:
    """A person rejected this invoice: tell the supplier why and ask for a corrected one (`reminder` > 0 makes it the
    n-th reminder rather than the first notice). Replying to this email
    (the subject carries the case reference) lands back on the same case. Never raises: a failure to email is
    recorded on the case, and the rejection stands either way. Returns whether the email went out."""
    problems = "\n".join(f"  - {p}" for p in invoice["issues"]) or "  - It could not be matched to our order."
    reason = f"\nNote from our accounts team: {decided_note.strip()}\n" if decided_note and decided_note.strip() else ""
    nudge = f"Reminder {reminder}: we are still waiting for a corrected invoice.\n\n" if reminder else ""
    body = (
        f"Dear {invoice['vendor_name']},\n\n{nudge}"
        f"We could not accept your invoice {invoice['invoice_number'] or '(number not readable)'} for order {invoice['po_number']}.\n\n"
        f"What did not match:\n{problems}\n{reason}\n"
        f"Please reply to this email with a corrected invoice (quote the order number {invoice['po_number']}, "
        f"the invoice number and the total).\n\nThank you."
    )
    sent = False
    if vendor_email:
        try:
            number = f" {invoice['invoice_number']}" if invoice["invoice_number"] else ""
            email_client.send_email(vendor_email, make_subject(invoice["case_id"], f"{'Reminder: ' if reminder else ''}Invoice{number} not accepted: corrected invoice needed"), body)
            sent = True
        except Exception:
            logger.exception("Could not email the supplier about the rejected invoice %s", invoice["invoice_id"])
    operations_agent.publish_event(
        invoice["case_id"], "invoice.chased" if reminder else "invoice.vendor_notified", agent_name="Invoice Agent",
        payload={"invoice_id": invoice["invoice_id"], "vendor": invoice["vendor_name"], "sent": sent, **({"reminder": reminder} if reminder else {}),
                 "reason": None if sent else ("The supplier has no email address." if not vendor_email else "The email could not be sent.")},
    )
    return sent


def get_invoice(invoice_id: str) -> dict:
    row = invoice_repository.find_by_id(invoice_id)
    if row is None:
        raise InvoiceNotFound(invoice_id)
    return _row_to_dict(row)


def get_invoices(case_id: str) -> list[dict]:
    return [_row_to_dict(r) for r in invoice_repository.find_by_case_id(case_id)]


def get_invoices_with_extraction(case_id: str) -> list[dict]:
    """The case's invoices plus, for each, the text as it arrived and what the AI read from it (staff views)."""
    seen = {str(r.invoice_id).lower(): r for r in invoice_repository.find_extractions_by_case_id(case_id)}
    out = []
    for invoice in get_invoices(case_id):
        row = seen.get(invoice["invoice_id"].lower())
        try:
            extracted = json.loads(row.extracted_json) if row and row.extracted_json else {}
        except ValueError:
            extracted = {}
        out.append({**invoice, "raw_text": row.raw_text if row else "", "extracted": extracted})
    return out


def list_invoices(status: str | None = None) -> list[dict]:
    return [_row_to_dict(r) for r in invoice_repository.find_all(status)]


def _clean_text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:100] or None


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "")) if value is not None else None
    except ValueError:
        return None


def _items(value) -> list[dict]:
    items = []
    for entry in value if isinstance(value, list) else []:
        try:
            items.append({"description": str(entry["description"])[:200], "quantity": int(entry["quantity"])})
        except (KeyError, TypeError, ValueError):
            continue
    return items


def _opt(value):
    return float(value) if value is not None else None


def _row_to_dict(row) -> dict:
    return {
        "invoice_id": str(row.invoice_id),
        "case_id": str(row.case_id),
        "purchase_order_id": str(row.purchase_order_id),
        "vendor_id": str(row.vendor_id),
        "vendor_name": row.vendor_name,
        "po_number": f"PO-{row.po_number}",
        "invoice_number": row.invoice_number,
        "total_amount": float(row.total_amount) if row.total_amount is not None else None,
        "subtotal": _opt(getattr(row, "subtotal", None)),
        "tax_rate_pct": _opt(getattr(row, "tax_rate_pct", None)),
        "tax_amount": _opt(getattr(row, "tax_amount", None)),
        "status": row.status,
        "issues": json.loads(row.issues) if row.issues else [],
        "source": row.source,
        "decided_by": row.decided_by,
        "decision_note": row.decision_note,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
    }
