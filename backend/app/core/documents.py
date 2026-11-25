"""What goes into the two printable documents: the purchase order and the one-page approval summary.

Pure functions: no database, clock or e-mail. The controller gathers the facts and these shape them; `pdf_render` draws them. Keeping
the content here means it can be tested without making a PDF, and the same facts could feed another format later."""

from datetime import date, datetime

from app.core import tax as tax_rules

MAX_OFFERS = 6                  # the summary is ONE page: show the best few offers and say how many were left out
MAX_TEXT = {"request": 420, "rationale": 520, "reason": 150, "note": 300, "terms": 120}

_REPLACE = {"₹": "Rs ", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "•": "-", "→": "->", " ": " ", "×": "x"}


def safe_text(value) -> str:
    """Text the built-in PDF fonts can draw (Latin-1): common punctuation and the rupee sign are written out, anything else becomes '?'.
    Names in other scripts (Devanagari...) would need an embedded font; the document says so rather than showing blanks."""
    text = "" if value is None else str(value)
    for old, new in _REPLACE.items():
        text = text.replace(old, new)
    return "".join(ch if ch == "\n" or (32 <= ord(ch) < 256) else "?" for ch in text)


def shorten(value, limit: int) -> str:
    text = " ".join(safe_text(value).split())
    return text if len(text) <= limit else text[: max(limit - 3, 0)].rstrip() + "..."


def money(amount) -> str:
    return "as per quotation" if amount is None else f"Rs {amount:,.2f}"


def _date(value) -> str:
    if isinstance(value, datetime):
        return f"{value:%d %b %Y}"
    return f"{value:%d %b %Y}" if isinstance(value, date) else ""


def file_name(prefix: str, number: str | None) -> str:
    """A safe download name such as PO-1005.pdf (letters, digits, dashes only)."""
    number = number or ""
    label = number if number.upper().startswith(prefix.upper() + "-") else f"{prefix}-{number}"        # "PO-12" is already "PO-12", not "PO-PO-12"
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label).strip("-")
    return f"{clean}.pdf"


def purchase_order(po: dict, vendor: dict | None, company: dict, case_number: str | None, requested_by: str | None) -> dict:
    """The purchase order as a document. `po` is the order as the PO agent holds it, `vendor` the supplier's details (may be missing)."""
    items = [{"no": i + 1, "description": safe_text(line.get("description")), "quantity": line.get("quantity")} for i, line in enumerate(po.get("items") or [])]
    return {
        "kind": "purchase_order",
        "title": "PURCHASE ORDER",
        "number": po["po_number"],
        "company": {"name": safe_text(company.get("name")), "address": [safe_text(x) for x in (company.get("address") or [])]},
        "issued": _date(po.get("sent_at") or po.get("created_at")),
        "case_number": case_number,
        "status": (po.get("status") or "").replace("_", " "),
        "vendor": {"name": safe_text(po.get("vendor_name")), "email": safe_text((vendor or {}).get("email") or po.get("vendor_email") or "")},
        "items": items,
        "total": money(po.get("total_amount")),
        "tax": ({"subtotal": money(order_tax["subtotal"]), "rate": f"{order_tax['rate_pct']:g}%", "amount": money(order_tax["tax_amount"]),
                 "total": money(order_tax["total_with_tax"])} if (order_tax := tax_rules.of_order(po)) else None),
        "delivery_by": _date(po.get("expected_delivery_date")) or "as per quotation",
        "lead_time": f"{po['lead_time_days']} days" if po.get("lead_time_days") is not None else None,
        "terms": shorten(po.get("terms"), 400) or "as per quotation",
        "requested_by": safe_text(requested_by or ""),
        "footer": f"Please confirm receipt of this order and quote {po['po_number']} on all invoices and delivery documents.",
    }


_DECISION = {"approved": "Approved", "rejected": "Rejected", "auto_approved": "Approved automatically (within the limits)", "pending": "Waiting for a decision"}


def approval_summary(review: dict, approval: dict, company: dict, po_number: str | None) -> dict:
    """One page: the request, the offers, what the AI thought, and what was decided. `review` is the approval review the app shows,
    `approval` the approval record (who decided and when)."""
    options = list(review.get("options") or [])
    chosen_id = review.get("selected_vendor_id")
    shown = options[:MAX_OFFERS]
    offers = []
    for o in shown:
        offers.append({
            "rank": o.get("rank"), "supplier": shorten(o.get("vendor_name"), 40), "price": money(o.get("price")) if o.get("price") is not None else "-",
            "lead_time": f"{o['lead_time_days']} days" if o.get("lead_time_days") is not None else "-",
            "reliability": f"{o['reliability']:.1f}" if o.get("reliability") is not None else "-",
            "terms": shorten(o.get("terms"), MAX_TEXT["terms"]) or "-", "tags": ", ".join(safe_text(t) for t in o.get("tags") or []),
            "reason": shorten(o.get("reason"), MAX_TEXT["reason"]), "chosen": o.get("vendor_id") == chosen_id and chosen_id is not None,
        })
    chosen = next((o for o in options if o.get("vendor_id") == chosen_id), None)
    status = approval.get("status") or review.get("status") or "pending"
    return {
        "kind": "approval_summary",
        "title": "APPROVAL SUMMARY",
        "company": {"name": safe_text(company.get("name")), "address": []},
        "case_number": review.get("case_number"),
        "requested_by": safe_text(review.get("requested_by") or ""),
        "needed_by": _date(review.get("needed_by")) or None,
        "urgent": bool(review.get("urgent")),
        "request_text": shorten(review.get("request_text"), MAX_TEXT["request"]),
        "items": [{"description": safe_text(i.get("description")), "quantity": i.get("quantity")} for i in review.get("items") or []],
        "why_a_person": [shorten(r, 200) for r in review.get("reasons") or []] or (["Within the automatic limits."] if status == "auto_approved" else []),
        "offers": offers,
        "offers_left_out": max(len(options) - len(shown), 0),
        "ai_pick": next((o["vendor_name"] for o in options if o.get("vendor_id") == review.get("recommended_vendor_id")), None),
        "ai_reasoning": shorten(review.get("rationale"), MAX_TEXT["rationale"]),
        "suggestion": shorten(review.get("suggestion"), 260),
        "decision": {
            "status": status, "label": _DECISION.get(status, status.replace("_", " ").capitalize()),
            "by": "the approval rules" if approval.get("decided_by") == "policy" else safe_text(approval.get("decided_by") or ""),
            "at": _date(approval.get("decided_at")), "note": shorten(approval.get("decision_note"), MAX_TEXT["note"]),
            "supplier": shorten(chosen["vendor_name"], 60) if chosen else None,
            "different_from_ai": bool(chosen and review.get("recommended_vendor_id") and chosen.get("vendor_id") != review.get("recommended_vendor_id")),
        },
        "po_number": po_number,
    }
