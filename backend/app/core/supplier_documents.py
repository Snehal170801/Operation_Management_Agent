"""What a supplier's email IS, decided from its text: our own purchase order sent back, a credit note, a proforma invoice, an out-of-office
reply, a refusal, a reply with no price. Pure functions over text: no database, clock or AI. The pipeline decides what to do about each
(see docs/PRODUCTION_READINESS_PLAN.md section 4); the rule here only says what it is, and errs on the side of "not sure" (None) so a
real quote or invoice is never swallowed by a guess."""

import re

# phrases our own order text and order PDF contain (see purchase_order_agent._po_body and core/documents.purchase_order)
_OWN_PO_MARKERS = (
    re.compile(r"please find our purchase order", re.I),
    re.compile(r"\bPURCHASE ORDER\b", re.I),
    re.compile(r"\bTotal amount\b", re.I),
    re.compile(r"\bDelivery by\b", re.I),
    re.compile(r"\bTerms\s*:", re.I),
    re.compile(r"please confirm receipt of this order", re.I),
    re.compile(r"on all invoices and delivery documents", re.I),
)
_INVOICE_SIGNS = re.compile(r"(tax\s+invoice|invoice\s*(?:no\.?|number|#|date)\b|\bGSTIN\b|\bbill\s+to\b)", re.I)
OWN_PO_MIN_MARKERS = 3


def is_own_purchase_order(text: str, po_number: str | None) -> bool:
    """The supplier sent our own order back (the PDF, or its text pasted) with nothing of theirs on it: it carries this order's number and
    our wording, and none of the signs of an invoice. A reply that merely quotes the order number, or an invoice naming it, is not this."""
    text = text or ""
    if not po_number or po_number.lower() not in text.lower() or _INVOICE_SIGNS.search(text):
        return False
    return sum(1 for marker in _OWN_PO_MARKERS if marker.search(text)) >= OWN_PO_MIN_MARKERS


_CREDIT_NOTE = re.compile(r"\bcredit[\s-]*(?:note|memo|advice)\b|\bCN[\s-]*(?:no\.?|number|#)\s*\w", re.I)
_PROFORMA = re.compile(r"\bpro[\s-]?forma\b", re.I)
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)


def is_credit_note(text: str) -> bool:
    """The supplier is giving money back (a credit note / credit memo), not billing us."""
    return bool(_CREDIT_NOTE.search(text or ""))


def credit_amount(text: str) -> float | None:
    """The amount the credit note is for, when one amount is clearly labelled (credit / total / amount); otherwise None.
    Never guesses: Accounts reads the document and applies the credit."""
    for label in re.finditer(r"(?:credit(?:\s+note)?(?:\s+(?:amount|total|value))?|total(?:\s+credit)?|amount)\s*[:\-]?\s*", text or "", re.I):
        found = _AMOUNT.match((text or "")[label.end():label.end() + 40])
        if found:
            try:
                return float(found.group(1).replace(",", ""))
            except ValueError:
                return None
    return None


def is_proforma_invoice(text: str) -> bool:
    """A proforma invoice is a quote-like preview, not a bill: it must not be matched or paid, and the final invoice is still due."""
    return bool(_PROFORMA.search(text or ""))


_HAS_PRICE = re.compile(r"(?:₹|\brs\.?|\binr\b)\s*[0-9]|[0-9][0-9,]*\.[0-9]{2}\b|\b[0-9]{1,3}(?:,[0-9]{2,3})+\b|\b[0-9]{3,}\b|\b[0-9]+(?:\.[0-9]+)?\s*(?:k|lakhs?|lacs?|crores?|thousand)\b|\b(?:price|total|rate|quotation|quote)\b[^.\n]{0,25}[0-9]", re.I)
_DECLINE = re.compile(
    r"\b(?:unable|not able|cannot|can ?not|can't|won't be able|will not be able|regret|unfortunately|sorry)\b[^.\n]{0,60}\b(?:supply|quote|quotation|provide|offer|fulfil|fulfill|deliver|stock)\b"
    r"|\b(?:not interested|no stock|out of stock|do(?:es)? not (?:supply|stock|deal in)|don't (?:supply|stock|deal in)|decline[ds]?|no longer (?:supply|stock|deal))\b", re.I)


def has_price(text: str) -> bool:
    """The text states some amount: a currency sign, a decimal, a grouped number, a number of three or more digits, or a price word then a number."""
    return bool(_HAS_PRICE.search(text or ""))


def is_decline(text: str) -> bool:
    """The supplier says they will not or cannot supply or quote, and gives no price (a quote that says 'we cannot deliver sooner, price Rs 40,000'
    is a quote, not a refusal)."""
    return bool(_DECLINE.search(text or "")) and not has_price(text)


def is_no_price(text: str) -> bool:
    """A reply that states no price at all (a question, 'we will revert', a request for specifications) and is not a refusal."""
    return bool((text or "").strip()) and not has_price(text) and not is_decline(text)


_AUTO_SUBJECT = re.compile(r"^\s*(?:(?:re|fwd?)\s*:\s*)*(?:automatic reply|auto[- ]?reply|autoreply|auto[- ]?response|out of (?:the )?office|away from (?:the )?office|vacation (?:reply|notice|response)|on leave)\b", re.I)
_AUTO_BODY = re.compile(r"\b(?:i am|i'm|we are|we're) (?:currently )?(?:out of (?:the )?office|away from (?:the )?(?:office|desk)|on (?:leave|vacation|holiday)|travelling)\b|\bthis is an automa(?:tic|ted) (?:reply|response|message)\b|\bautomatic reply\b|\bwill (?:be back|return|respond|reply) (?:on|after|when|from)\b[^.\n]{0,40}\b(?:return|back)\b", re.I)
AUTO_BODY_MAX_CHARS = 900


def is_auto_reply(subject: str | None, body: str | None) -> bool:
    """An out-of-office / automatic reply: it says nothing about the order and must not be answered (two auto-responders would write to
    each other for ever), read as a quote, or counted as the supplier replying. A subject that begins with the usual auto-reply words is
    enough; in the body the wording only counts when the message is short, so a real quote that mentions a colleague being away is not dropped."""
    if _AUTO_SUBJECT.search(subject or ""):
        return True
    body = body or ""
    return len(body) <= AUTO_BODY_MAX_CHARS and bool(_AUTO_BODY.search(body)) and not has_price(body)


# ---- a supplier asks a question ------------------------------------------------------------------------------------------------------------

_QUESTION_WORDS = re.compile(r"\b(?:could you|can you|would you|will you|please (?:clarify|confirm|advise|specify|share|send)|which|what|when|how (?:many|much)|do you need|"
                             r"need (?:more )?(?:details|information|clarification|specifications?)|clarif\w+|specifications?)\b", re.I)


def is_question(text: str) -> bool:
    """The supplier is asking us something (a '?' or question wording) and has not given a price. The Vendor team answers; we do not
    chase them for a price while they are waiting on us."""
    text = text or ""
    return bool(text.strip()) and not has_price(text) and not is_decline(text) and ("?" in text or bool(_QUESTION_WORDS.search(text)))


# ---- a quote that covers only some of the items ------------------------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]{3,}", re.I)
_FILLER = frozenset({"the", "and", "for", "with", "set", "pcs", "unit", "units", "item", "items", "type", "new"})


def _keys(description: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(description or "") if w.lower() not in _FILLER}


def items_missing_from_quote(items: list[str], text: str) -> list[str]:
    """For a request of two or more items: the items the quote does not mention, but only when it DOES mention at least one of the others
    (it itemises, and skipped some). A quote that is one total with no item names says nothing about coverage, so nothing is flagged."""
    if len(items) < 2:
        return []
    low = (text or "").lower()
    mentioned = [i for i in items if (keys := _keys(i)) and any(k in low for k in keys)]
    if not mentioned or len(mentioned) == len(items):
        return []
    return [i for i in items if i not in mentioned]


# ---- file types ----------------------------------------------------------------------------------------------------------------------------------

READABLE_SUFFIXES = (".pdf", ".xlsx", ".csv", ".txt", ".jpg", ".jpeg", ".png")


def unsupported_files(attachments: list[dict]) -> list[str]:
    """Attached files of a kind we do not read at all (a zip, a Word file, an old .xls...): the mail's words may still be read, but a person
    must know a file was skipped. Judged by the name alone."""
    return [a.get("name") or "(unnamed)" for a in attachments or [] if not (a.get("name") or "").lower().endswith(READABLE_SUFFIXES)]


# ---- "it has been delivered" ---------------------------------------------------------------------------------------------------------------------

_DELIVERED = re.compile(r"\b(?:(?:has|have|had|was|were|been)\s+(?:been\s+)?(?:successfully\s+)?delivered|delivered\s+(?:to you|at your|on|today|yesterday|successfully)|"
                        r"(?:we|i)\s+(?:have\s+)?(?:delivered|handed over)|goods\s+(?:are\s+)?delivered|delivery\s+(?:is\s+)?(?:done|complete[d]?))\b", re.I)
_NOT_YET = re.compile(r"\b(?:will be|to be|going to be|shall be|not yet|not been|hasn'?t been|haven'?t|cannot be|can'?t be|unable to|before it is|once (?:it is )?)\s+(?:\w+\s+){0,2}delivered\b|\bnot delivered\b", re.I)


def is_delivery_claim(text: str) -> bool:
    """The supplier says the goods have been delivered. Only a claim: Receiving must verify, the goods are NOT marked received."""
    text = text or ""
    return bool(_DELIVERED.search(text)) and not _NOT_YET.search(text)
