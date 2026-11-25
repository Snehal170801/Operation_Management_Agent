"""The remaining supplier-document cases of docs/PRODUCTION_READINESS_PLAN.md section 4: a question, a partial quote, the same email twice,
an unsupported file, an invoice after the case closed, and a 'delivered' claim. Each ends as one visible result and a person told."""

import pytest

from app.core import supplier_documents as docs
from app.orchestrator import case_pipeline

from .fake_world import standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source


@pytest.fixture
def w(monkeypatch):
    return standard_world(monkeypatch)


def alerts(w, text):
    return [m for m in w.emails_to("manager@x.co") if text in m[2]]


def ordered(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


# ---- the rules --------------------------------------------------------------------------------------------------------------------------

def test_a_question_is_a_question_only_when_there_is_no_price_and_no_refusal():
    assert docs.is_question("Could you share the model number?") and docs.is_question("Please clarify the quantity")
    assert not docs.is_question("Total Rs 42,000, which model?") and not docs.is_question("We will revert tomorrow")
    assert not docs.is_question("Sorry, we cannot supply. Why do you ask?") and not docs.is_question("")


def test_partial_means_it_names_some_items_and_skips_others():
    two = ["CCTV camera", "Network switch"]
    assert docs.items_missing_from_quote(two, "CCTV camera x 50 at Rs 40,000 total") == ["Network switch"]
    assert docs.items_missing_from_quote(two, "Total Rs 42,000") == []                          # one total, no item names: says nothing about coverage
    assert docs.items_missing_from_quote(two, "cctv camera and network switch, Rs 90,000") == []
    assert docs.items_missing_from_quote(["Cable"], "something else") == [] and docs.items_missing_from_quote([], "x") == []


def test_unsupported_files_are_judged_by_their_name():
    assert docs.unsupported_files([{"name": "a.ZIP"}, {"name": "b.pdf"}, {"name": "c.xls"}, {"name": "d.docx"}, {"name": "e.XLSX"}]) == ["a.ZIP", "c.xls", "d.docx"]
    assert docs.unsupported_files([]) == [] and docs.unsupported_files(None) == []


def test_a_delivery_claim_is_a_past_tense_claim_not_a_promise_or_a_denial():
    for yes in ("The goods have been delivered to your site", "We delivered the order yesterday", "Delivery is complete", "Order was delivered successfully"):
        assert docs.is_delivery_claim(yes), yes
    for no in ("Goods will be delivered on Friday", "It has not been delivered yet", "To be delivered next week", "Thanks for your order", ""):
        assert not docs.is_delivery_claim(no), no


# ---- a supplier asks a question ---------------------------------------------------------------------------------------------------------

def test_a_question_tells_the_vendor_team_notes_the_case_and_keeps_waiting_without_chasing(w):
    case_id = w.submit("50 cameras")
    before = len(w.sent)
    assert w.reply(case_id, "Acme", "Which model of camera do you need?") == "question"
    assert "quote.question" in w.event_types(case_id) and alerts(w, "has a question before they can quote")
    assert not [m for m in w.sent[before:] if m[0] == "acme@vendor.com"]                         # nothing sent back to them: no "please send a price" while they wait on us
    assert [r.status for r in w.rfqs if r.case_id == case_id and r.vendor_name == "Acme"] == ["sent"] and w.stage(case_id) == "awaiting_quotes"
    assert not [q for q in w.quotes if q.case_id == case_id]


def test_after_the_question_is_answered_the_quote_still_counts(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "Which model do you need?")
    assert w.reply(case_id, "Acme", QUOTE_42K) == "quoted"


# ---- a quote for only some items --------------------------------------------------------------------------------------------------------

def test_a_quote_that_skips_an_item_is_flagged_but_still_counted(w):
    w.teach("cameras and switches", [{"description": "CCTV camera", "quantity": 50}, {"description": "Network switch", "quantity": 5}])
    case_id = w.submit("cameras and switches")
    assert w.reply(case_id, "Acme", "CCTV camera x 50, total Rs 42,000, delivery 7 days, 50% advance.") == "quoted"
    assert "quote.partial" in w.event_types(case_id) and alerts(w, "does not mention: Network switch")
    assert len([q for q in w.quotes if q.case_id == case_id]) == 1


def test_a_quote_naming_every_item_or_one_total_is_not_flagged(w):
    w.teach("cameras and switches", [{"description": "CCTV camera", "quantity": 50}, {"description": "Network switch", "quantity": 5}])
    case_id = w.submit("cameras and switches")
    w.reply(case_id, "Acme", "CCTV camera and network switch, total Rs 42,000, 7 days.")
    w.reply(case_id, "Globex", QUOTE_45K)
    assert "quote.partial" not in w.event_types(case_id)


def test_a_failure_while_checking_coverage_never_loses_the_quote(w, monkeypatch):
    case_id = w.submit("50 cameras")
    monkeypatch.setattr(case_pipeline.supplier_documents, "items_missing_from_quote", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert w.reply(case_id, "Acme", QUOTE_42K) == "quoted"


# ---- the same email twice -----------------------------------------------------------------------------------------------------------------

def test_the_same_email_twice_is_noted_and_handled_once(w):
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", QUOTE_42K) == "quoted"
    assert w.reply(case_id, "Acme", QUOTE_42K) == "duplicate_email"
    assert "email.duplicate" in w.event_types(case_id) and len([q for q in w.quotes if q.case_id == case_id]) == 1


def test_a_different_email_from_the_same_supplier_and_the_same_words_from_another_supplier_are_both_handled(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", QUOTE_42K)
    assert w.reply(case_id, "Acme", QUOTE_45K) != "duplicate_email"
    assert w.reply(case_id, "Globex", QUOTE_42K) == "quoted"


def test_the_same_words_on_another_case_are_handled(w):
    first, second = w.submit("50 cameras"), w.submit("50 cameras")
    w.reply(first, "Acme", QUOTE_42K)
    assert w.reply(second, "Acme", QUOTE_42K) == "quoted"


# ---- a file of a kind we do not read ----------------------------------------------------------------------------------------------------

def test_a_zip_with_a_readable_email_notes_the_skipped_file_asks_for_a_pdf_and_still_reads_the_words(w):
    case_id = w.submit("50 cameras")
    before = len(w.sent)
    assert w.reply(case_id, "Acme", QUOTE_42K, attachments=[{"name": "details.zip", "text": None}]) == "quoted"
    assert "document.unsupported_file" in w.event_types(case_id) and alerts(w, "details.zip")
    assert sum(1 for m in w.sent[before:] if "could not read" in m[1].lower() or "resend" in m[1].lower()) == 1


def test_a_zip_with_nothing_else_is_the_unreadable_rule_not_announced_twice(w):
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "all.zip", "text": None}]) == "empty"
    assert "document.unreadable" in w.event_types(case_id) and "document.unsupported_file" not in w.event_types(case_id)


def test_asking_for_a_resend_stops_after_two_asks(w):
    case_id = w.submit("50 cameras")
    for n in range(4):
        w.reply(case_id, "Acme", f"Total Rs {40000 + n}, 7 days.", attachments=[{"name": f"d{n}.zip", "text": None}])
    assert sum(1 for m in w.sent if "resend" in m[1].lower() or "could not read" in m[1].lower()) == 2


# ---- an invoice after the case was closed -----------------------------------------------------------------------------------------------

def test_an_invoice_after_the_case_closed_is_flagged_to_accounts_as_a_possible_duplicate(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    w.reply(case_id, "Acme", "Invoice INV-1 for PO-1001. Total Rs 42,000. 50 x CCTV camera.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert w.stage(case_id) == "completed" and "invoice.after_close" not in w.event_types(case_id)       # the first one closes it quietly
    w.reply(case_id, "Acme", "Invoice INV-2 for PO-1001. Total Rs 42,000. 50 x CCTV camera.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert "invoice.after_close" in w.event_types(case_id) and alerts(w, "AFTER the request was closed")


# ---- "it has been delivered" ---------------------------------------------------------------------------------------------------------------

def test_a_delivered_claim_asks_receiving_to_verify_and_does_not_mark_anything_received(w):
    case_id = ordered(w)
    assert w.reply(case_id, "Acme", "Good news, the goods have been delivered to your site today.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001") == "delivery_claimed"
    assert "delivery.claimed_by_supplier" in w.event_types(case_id) and alerts(w, "Nothing was marked received")
    assert w.pos[case_id].delivery_status == "pending" and w.stage(case_id) == "po_issued"


def test_a_promise_to_deliver_is_not_a_claim_and_a_claim_after_receipt_is_not_repeated(w):
    case_id = ordered(w)
    assert w.reply(case_id, "Acme", "The goods will be delivered on Friday.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001") != "delivery_claimed"
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    assert w.reply(case_id, "Acme", "As discussed, the goods have been delivered.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001") != "delivery_claimed"
