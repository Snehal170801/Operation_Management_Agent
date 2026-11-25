"""What a supplier's email is, and what the system does about each kind (docs/PRODUCTION_READINESS_PLAN.md section 4): one visible result,
and a person told when one is needed."""

import pytest

from app.core import supplier_documents as docs
from app.orchestrator import case_pipeline

from .fake_world import standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

PO = "PO-1007"
OUR_ORDER = ("Dear Acme,\n\nFurther to your quotation, please find our purchase order PO-1007.\n\nItems:\n  - CCTV camera x 50\n\n"
             "Total amount: 42,000.00\nDelivery by: 12 Oct 2026\nTerms: 50% advance\n\nPlease confirm receipt of this order by replying to this email.")


@pytest.fixture
def w(monkeypatch):
    return standard_world(monkeypatch)


def ordered(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def alerts(w, text):
    return [m for m in w.emails_to("manager@x.co") if text in m[2]]


# ---- our own purchase order sent back (rule) ------------------------------------------------------------------------------------------

def test_our_own_order_is_recognised_by_its_number_and_wording():
    assert docs.is_own_purchase_order(OUR_ORDER, PO)
    assert docs.is_own_purchase_order("PURCHASE ORDER\nPO-1007\nTotal amount Rs 1\nDelivery by 1 Oct\nTerms: x", "po-1007")


def test_a_reply_that_only_mentions_the_number_or_an_invoice_for_it_is_not_our_order_back():
    assert not docs.is_own_purchase_order("Confirmed, we will deliver PO-1007 on Friday.", PO)
    assert not docs.is_own_purchase_order(OUR_ORDER + "\nTax Invoice No. 55", PO)             # an invoice that repeats our wording
    assert not docs.is_own_purchase_order(OUR_ORDER, "PO-9999")                              # another order's number
    assert not docs.is_own_purchase_order(OUR_ORDER, None) and not docs.is_own_purchase_order("", PO)


# ---- our own purchase order sent back (pipeline) ----------------------------------------------------------------------------------------

def test_our_order_sent_back_is_logged_the_po_desk_told_and_the_supplier_asked_once(w):
    case_id = ordered(w)
    po = w.pos[case_id]
    text = OUR_ORDER.replace("PO-1007", f"PO-{po.po_number}")
    before = len(w.sent)
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "order.pdf", "text": text}]) == "own_po_returned"
    assert "po.returned_unchanged" in w.event_types(case_id)
    assert alerts(w, "sent back our own purchase order")
    assert sum(1 for m in w.sent[before:] if "what do you need" in m[1]) == 1
    assert w.stage(case_id) == "po_issued" and not w.invoices                    # nothing was read as an invoice


def test_a_second_copy_is_logged_but_neither_asks_nor_alerts_again(w):
    case_id = ordered(w)
    text = OUR_ORDER.replace("PO-1007", f"PO-{w.pos[case_id].po_number}")
    w.reply(case_id, "Acme", "", attachments=[{"name": "order.pdf", "text": text}])
    mails, alerts_before = len(w.sent), len(alerts(w, "sent back our own"))
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "again.pdf", "text": text}]) == "duplicate_file"          # the very same file: noted, not read again
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "again.pdf", "text": text + " Signed."}]) == "own_po_returned"   # a changed copy is read, but only logged
    assert len(w.sent) == mails and len(alerts(w, "sent back our own")) == alerts_before
    assert w.event_types(case_id).count("po.returned_unchanged") == 2


def test_a_supplier_without_an_address_still_makes_the_po_desk_hear_about_it(w):
    case_id = ordered(w)
    po = w.pos[case_id]
    po.vendor_email = None
    text = OUR_ORDER.replace("PO-1007", f"PO-{po.po_number}")
    assert case_pipeline._react_to_returned_order(case_id, case_pipeline.purchase_order_agent.find_purchase_order(case_id),
                                                  {"from_email": "x@y.z", "attachments": [{"name": "o.pdf", "text": text}]}) == "own_po_returned"
    assert alerts(w, "could not be asked by email")


# ---- not fooled (a9's extra case) ------------------------------------------------------------------------------------------------------

def test_a_plain_confirmation_quoting_our_whole_order_is_not_the_order_returned(w):
    case_id = ordered(w)
    po = w.pos[case_id]
    quoted = "Confirmed, thanks.\n\nOn Mon, 5 Oct 2026, Ops <ops@x.com> wrote:\n" + "\n".join("> " + line for line in OUR_ORDER.replace("PO-1007", f"PO-{po.po_number}").splitlines())
    assert w.reply(case_id, "Acme", quoted) != "own_po_returned"
    assert "po.returned_unchanged" not in w.event_types(case_id)


def test_a_real_invoice_naming_the_order_is_not_the_order_returned(w):
    case_id = ordered(w)
    po = w.pos[case_id]
    invoice = f"TAX INVOICE\nInvoice No. INV-77\nPurchase order {po_number(po)}\nTotal amount: 42,000.00\nDelivery by 12 Oct\nTerms: net 30"
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "inv.pdf", "text": invoice}]) != "own_po_returned"
    assert "po.returned_unchanged" not in w.event_types(case_id)


def po_number(po):
    return f"PO-{po.po_number}"


# ---- credit note ------------------------------------------------------------------------------------------------------------------------

def test_credit_notes_are_recognised_and_the_amount_read_only_when_it_is_clear():
    assert docs.is_credit_note("Please find attached Credit Note CN-12 for the returned goods")
    assert docs.is_credit_note("our credit memo is attached") and not docs.is_credit_note("Invoice INV-1 total 500; no credit applied")
    assert docs.credit_amount("Credit note amount: Rs 1,250.50 against PO-1") == 1250.5
    assert docs.credit_amount("Credit note attached, see PDF") is None
    assert docs.credit_amount("Invoice for 40 units, Rs 500") is None                       # an unlabelled amount is never guessed


def test_a_credit_note_is_logged_not_matched_and_accounts_is_told(w):
    case_id = ordered(w)
    assert w.reply(case_id, "Acme", f"Credit note CN-9 for PO-{w.pos[case_id].po_number}. Credit amount: Rs 2,000") == "credit_note"
    assert "invoice.credit_note" in w.event_types(case_id) and not w.invoices                # not recorded as an invoice (no false mismatch)
    assert alerts(w, "sent a credit note for Rs 2,000.00")


def test_a_credit_note_with_no_readable_amount_still_tells_accounts_and_says_so(w):
    case_id = ordered(w)
    assert w.reply(case_id, "Acme", "Our credit note is attached.") == "credit_note"
    assert alerts(w, "amount could not be read")


# ---- proforma invoice -------------------------------------------------------------------------------------------------------------------

def test_a_proforma_is_recognised_by_its_name_only():
    assert docs.is_proforma_invoice("Proforma Invoice PI-4") and docs.is_proforma_invoice("PRO-FORMA invoice") and docs.is_proforma_invoice("pro forma")
    assert not docs.is_proforma_invoice("Tax Invoice INV-1, as a formality we enclose it") and not docs.is_proforma_invoice("")


def test_a_proforma_is_not_matched_or_paid_the_final_invoice_is_asked_for_once_and_accounts_told(w):
    case_id = ordered(w)
    before = len(w.sent)
    assert w.reply(case_id, "Acme", "Proforma invoice PI-3, total 42,000") == "proforma"
    assert not w.invoices and "invoice.proforma" in w.event_types(case_id)
    assert sum(1 for m in w.sent[before:] if "Final invoice needed" in m[1]) == 1 and alerts(w, "proforma invoice")
    mails, seen = len(w.sent), len(alerts(w, "proforma invoice"))
    assert w.reply(case_id, "Acme", "Proforma invoice PI-3 again") == "proforma"
    assert len(w.sent) == mails and len(alerts(w, "proforma invoice")) == seen              # a repeat only logs: no loop, no spam


# ---- reply with no price / supplier declines ----------------------------------------------------------------------------------------------

def test_prices_are_found_in_the_usual_ways_and_missing_ones_are_noticed():
    for priced in ("Total Rs 42,000", "₹42000", "price is 42000", "we can do it for 42k", "42,000.00", "Total: 45 lakh", "quotation 5000 delivery 7 days"):
        assert docs.has_price(priced), priced
    for unpriced in ("Thanks, we will revert shortly", "Please send the specifications", "Do you need 50 cameras? 7 days is possible", ""):
        assert not docs.has_price(unpriced), unpriced


def test_a_refusal_with_no_price_is_a_decline_but_a_quote_that_mentions_what_it_cannot_do_is_not():
    assert docs.is_decline("Sorry, we are unable to supply these items.") and docs.is_decline("We do not stock CCTV cameras")
    assert docs.is_decline("Unfortunately we cannot quote for this.")
    assert not docs.is_decline("We cannot deliver in 3 days, but Rs 42,000 with 7 days works")
    assert not docs.is_decline("We will revert tomorrow")
    assert docs.is_no_price("Could you share the model number?") and not docs.is_no_price("Sorry, we cannot supply.") and not docs.is_no_price("   ")


def test_a_reply_with_no_price_is_logged_the_team_told_the_supplier_asked_once_and_still_waited_on(w):
    case_id = w.submit("50 cameras")
    before = len(w.sent)
    assert w.reply(case_id, "Acme", "Thanks, we will revert shortly.") == "no_price"
    assert "quote.no_price" in w.event_types(case_id) and alerts(w, "replied without a price")
    assert sum(1 for m in w.sent[before:] if "Your price is needed" in m[1]) == 1
    assert [r.status for r in w.rfqs if r.case_id == case_id and r.vendor_name == "Acme"] == ["sent"]      # not counted as an answer
    assert not [q for q in w.quotes if q.case_id == case_id]
    mails, seen = len(w.sent), len(alerts(w, "replied without a price"))
    assert w.reply(case_id, "Acme", "Still checking") == "no_price"
    assert len(w.sent) == mails and len(alerts(w, "replied without a price")) == seen                  # no loop


def test_a_decline_counts_as_an_answer_without_a_quote_and_the_vendor_team_is_told(w):
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", "Sorry, we are unable to supply these.") == "declined"
    assert [r.status for r in w.rfqs if r.case_id == case_id and r.vendor_name == "Acme"] == ["replied"]
    assert "quote.declined" in w.event_types(case_id) and alerts(w, "cannot supply")
    assert not [q for q in w.quotes if q.case_id == case_id] and w.stage(case_id) == "awaiting_quotes"      # the others are still being waited on


def test_when_the_others_quote_after_one_declines_the_request_goes_on_to_approval(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "We do not stock cameras, sorry.")
    w.reply(case_id, "Globex", QUOTE_45K)
    w.reply(case_id, "Initech", QUOTE_42K)
    assert w.stage(case_id) in ("awaiting_approval", "po_issued")


def test_when_every_supplier_declines_a_person_is_asked_at_once_with_the_right_reason(w):
    case_id = w.submit("50 cameras")
    for name in ("Acme", "Globex", "Initech"):
        w.reply(case_id, name, "Unfortunately we are unable to quote for this.")
    assert w.stage(case_id) == "sourcing_stalled"
    assert alerts(w, "none gave a price")


def test_a_real_quote_is_never_taken_for_a_decline_or_a_missing_price(w):
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", QUOTE_42K) == "quoted"
    assert w.reply(case_id, "Globex", "We cannot deliver in 3 days but Rs 45,000 total, 7 days, works.") == "quoted"


# ---- out-of-office auto-reply -----------------------------------------------------------------------------------------------------------

def test_auto_replies_are_recognised_by_subject_or_a_short_body_and_real_quotes_are_not():
    assert docs.is_auto_reply("Automatic reply: RE: [OA-1] Request for quotation", "x") and docs.is_auto_reply("Out of Office", "")
    assert docs.is_auto_reply("RE: [OA-1] Request", "I am currently out of the office until Monday 12 October. I will respond on my return.")
    assert docs.is_auto_reply("Re: Auto-Reply", "x") and docs.is_auto_reply("AutoReply: hello", "")
    assert not docs.is_auto_reply("RE: [OA-1] Request for quotation", "Total Rs 42,000, delivery 7 days.")
    assert not docs.is_auto_reply("RE: [OA-1] Request", "Priya is out of the office this week so I am replying: total price is 42000")
    long_quote = "I am out of the office on Friday. " + "Details of our offer. " * 80 + " Total 42,000"
    assert not docs.is_auto_reply("RE: [OA-1] Request", long_quote)


def test_an_out_of_office_reply_is_ignored_noted_on_the_case_never_answered_and_not_counted_as_a_reply(w):
    case_id = w.submit("50 cameras")
    before = len(w.sent)
    assert w.reply(case_id, "Acme", "I am out of the office until Monday. This is an automatic reply.",
                   subject=f"Automatic reply: RE: [OA-{case_id}] Request for quotation") == "auto_reply"
    assert "email.auto_reply" in w.event_types(case_id) and len(w.sent) == before                    # nothing sent back: no loop
    assert [r.status for r in w.rfqs if r.case_id == case_id and r.vendor_name == "Acme"] == ["sent"]
    assert not [q for q in w.quotes if q.case_id == case_id]


def test_an_out_of_office_reply_with_no_case_or_an_unknown_case_is_dropped_quietly(w):
    assert w.reply("x", "Acme", "I am on leave.", subject="Out of office", tagged=False) == "auto_reply"
    assert w.reply("00000000-0000-0000-0000-000000000000", "Acme", "", subject="Automatic reply: RE: [OA-00000000-0000-0000-0000-000000000000] x") == "auto_reply"


def test_the_reply_after_the_auto_reply_still_counts(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "", subject=f"Out of office: RE: [OA-{case_id}] Request for quotation")
    assert w.reply(case_id, "Acme", QUOTE_42K) == "quoted"
