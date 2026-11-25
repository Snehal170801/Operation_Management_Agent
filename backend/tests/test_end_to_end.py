"""The whole procure-to-pay flow, run through the REAL agents, policies and pipeline.
Only the database, email and AI are faked (see fake_world.py), so these tests catch wiring
mistakes between steps that the focused unit tests cannot."""

from datetime import date, timedelta

import pytest

from app.orchestrator import case_pipeline

from .fake_world import World, now, standard_world

QUOTE_42K = "Total Rs 42,000. Delivery 7 days. Terms: 50% advance"
QUOTE_45K = "Total Rs 45,000. Delivery 5 days. Terms: net 30"
QUOTE_90K = "Total Rs 90,000. Delivery 7 days. Terms: 50% advance"


@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def source(w: World, case_id: str, quotes: dict[str, str]):
    """Suppliers reply by email, then the quote deadline passes so the worker moves on."""
    for vendor, text in quotes.items():
        assert w.reply(case_id, vendor, text) == "quoted"
    w.expire_quote_deadline(case_id)
    w.tick()


# ---------- path 1: enough stock ----------

def test_enough_stock_dispatches_and_closes_with_no_emails(w):
    case_id = w.submit("10 laptops")
    assert w.stage(case_id) == "fulfilled_from_stock" and w.cases[case_id].status == "closed"
    assert w.stock["laptop"].quantity_available == 90
    assert w.sent == []


# ---------- path 2: routine purchase, no human anywhere ----------

def test_routine_purchase_runs_start_to_finish_without_a_human(w):
    case_id = w.submit("50 cameras")

    # not enough stock: every supplier with an email is asked for a price
    assert w.stage(case_id) == "awaiting_quotes"
    rfq_mails = [m for m in w.sent if "Request for quotation" in m[1]]
    assert sorted(m[0] for m in rfq_mails) == ["acme@vendor.com", "globex@vendor.com", "initech@vendor.com"]
    assert all(f"[OA-{case_id}]" in m[1] for m in rfq_mails)
    assert all("CCTV camera x 50" in m[2] for m in rfq_mails)

    # two trusted suppliers reply; the deadline passes; the worker ranks and approves by policy
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.selections[case_id].vendor_name == "Acme"
    assert [a.status for a in w.approvals] == ["auto_approved"]
    assert w.stage(case_id) == "po_issued"

    # a purchase order went to the chosen supplier with the agreed terms
    po = w.pos[case_id]
    assert po.status == "sent" and po.total_amount == 42000.0 and po.vendor_name == "Acme"
    to, subject, body = w.emails_to("acme@vendor.com")[-1]
    assert subject == f"[OA-{case_id}] Purchase Order PO-1001"
    assert "42,000.00" in body and "50% advance" in body and "CCTV camera x 50" in body
    assert w.emails_to("manager@x.co") == []     # nobody was disturbed

    # goods arrive (a person confirms), then the supplier's invoice arrives by email and clears itself
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", "all boxes ok")
    assert w.stage(case_id) == "delivered"
    outcome = w.reply(case_id, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.",
                      subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert outcome == "invoiced"
    assert w.invoices[0].status == "matched"
    assert w.stage(case_id) == "completed" and w.cases[case_id].status == "closed"
    assert w.emails_to("manager@x.co") == []     # still no human involved, start to finish


def test_the_timeline_tells_the_whole_story_in_order(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    w.reply(case_id, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.",
            subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    types = [t for t in w.event_types(case_id) if not t.startswith(("stage.", "step."))]
    expected = ["case.created", "purchase_request.created", "stock.checked", "rfq.sent", "quote.submitted",
                "quote.submitted", "vendor.selected", "approval.auto_approved", "po.issued",
                "delivery.received", "po.confirmed", "invoice.matched", "case.closed"]     # the invoice also shows the supplier has the order
    assert types == expected


# ---------- path 3: something unusual, a person decides ----------

def test_a_big_order_waits_for_a_manager_then_flows_on(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_90K, "Globex": "Total Rs 95,000. Delivery 7 days. Terms: net 30"})

    assert w.stage(case_id) == "awaiting_approval" and case_id not in w.pos      # no order yet
    approval = next(a for a in w.approvals if a.status == "pending")
    assert "exceeds the auto-approve limit" in approval.reasons
    alert = w.emails_to("manager@x.co")[-1]
    assert "Acme" in alert[2] and "exceeds the auto-approve limit" in alert[2]

    case_pipeline.decide_approval(approval.approval_id, True, "manager@x.co", "ok, urgent")
    assert w.pos[case_id].status == "sent" and w.stage(case_id) == "po_issued"
    assert w.emails_to("acme@vendor.com")[-1][1].endswith("Purchase Order PO-1001")


def test_an_untrusted_supplier_is_never_auto_approved(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Initech": "Total Rs 10,000. Delivery 3 days. Terms: net 30", "Acme": QUOTE_42K})
    # Initech is cheapest but has a reliability of 3.0, so a person must agree
    assert w.selections[case_id].vendor_name == "Initech"
    assert w.stage(case_id) == "awaiting_approval" and case_id not in w.pos


def test_a_single_quote_needs_a_person(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K})
    assert w.stage(case_id) == "awaiting_approval"


def test_a_rejection_closes_the_case_and_places_no_order(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_90K, "Globex": QUOTE_90K})
    approval = next(a for a in w.approvals if a.status == "pending")
    case_pipeline.decide_approval(approval.approval_id, False, "manager@x.co", "too expensive")
    assert w.stage(case_id) == "rejected" and w.cases[case_id].status == "closed"
    assert case_id not in w.pos


def test_the_daily_auto_spend_cap_pulls_in_a_person(w, monkeypatch):
    from app.repositories import purchase_order_repository
    monkeypatch.setattr(purchase_order_repository, "sum_auto_approved_since", lambda since: 190000.0)
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "awaiting_approval"
    assert "daily limit" in next(a for a in w.approvals).reasons


# ---------- path 4: nothing comes back ----------

def test_no_quotes_alerts_a_manager_instead_of_waiting_forever(w):
    case_id = w.submit("50 cameras")
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "sourcing_stalled"
    assert "No vendor quotes" in w.emails_to("manager@x.co")[-1][2]
    w.tick()
    assert len(w.emails_to("manager@x.co")) == 1          # told once, not every minute


def test_silent_suppliers_are_reminded_before_the_deadline(w):
    case_id = w.submit("50 cameras")
    for r in w.rfqs:
        r.last_contacted_at = now() - timedelta(hours=25)
    w.tick()
    reminders = [m for m in w.sent if "Reminder" in m[2]]
    assert len(reminders) == 3 and w.stage(case_id) == "awaiting_quotes"


def test_no_supplier_has_an_email_alerts_a_manager_immediately(w):
    for v in w.vendors.values():
        v.email = None
    case_id = w.submit("50 cameras")
    assert w.stage(case_id) == "sourcing_stalled"
    assert w.emails_to("manager@x.co")


# ---------- path 5: delivery goes wrong ----------

def _ordered_case(w) -> str:
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def test_a_late_supplier_is_chased_then_a_human_is_told(w):
    case_id = _ordered_case(w)
    po = w.pos[case_id]
    po.expected_delivery_date = date.today() - timedelta(days=2)

    w.tick()                                                    # first chase
    assert po.chase_count == 1
    assert "Delivery follow-up" in w.emails_to("acme@vendor.com")[-1][1]
    po.last_chased_at = now() - timedelta(hours=25)
    w.tick()                                                    # second chase
    assert po.chase_count == 2
    po.last_chased_at = now() - timedelta(hours=25)
    w.tick()                                                    # out of chases: a person is told
    assert w.stage(case_id) == "delivery_late" and po.escalated_at is not None
    assert "still not delivered" in w.emails_to("manager@x.co")[-1][2]
    w.tick()
    assert len([m for m in w.emails_to("manager@x.co") if "still not delivered" in m[2]]) == 1


def test_an_on_time_delivery_is_left_alone(w):
    case_id = _ordered_case(w)
    before = len(w.sent)
    w.tick()
    assert len(w.sent) == before and w.pos[case_id].chase_count == 0


# ---------- path 6: the invoice ----------

def test_an_invoice_before_delivery_waits_then_clears_when_goods_arrive(w):
    case_id = _ordered_case(w)
    w.reply(case_id, "Acme", "Invoice INV-9 for PO-1001. Total Rs 42,000. 50 x CCTV camera.",
            subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert w.invoices[0].status == "on_hold" and w.cases[case_id].status == "open"
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    assert w.invoices[0].status == "matched" and w.stage(case_id) == "completed"


def test_a_wrong_invoice_is_flagged_and_a_person_can_overrule(w):
    case_id = _ordered_case(w)
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    w.reply(case_id, "Acme", "Invoice INV-9 for PO-1001. Total Rs 49,000. 50 x CCTV camera.",
            subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    invoice = w.invoices[0]
    assert invoice.status == "mismatch" and w.cases[case_id].status == "open"
    assert "49,000.00" in w.emails_to("manager@x.co")[-1][2]

    case_pipeline.decide_invoice(invoice.invoice_id, True, "manager@x.co", "discount agreed by phone")
    assert w.stage(case_id) == "completed" and w.cases[case_id].status == "closed"


def test_the_same_invoice_sent_twice_is_not_paid_twice(w):
    case_id = _ordered_case(w)
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    text = "Invoice INV-9 for PO-1001. Total Rs 42,000. 50 x CCTV camera."
    subject = f"RE: [OA-{case_id}] Purchase Order PO-1001"
    w.reply(case_id, "Acme", text, subject=subject)
    w.reply(case_id, "Acme", text, subject=subject)
    assert [i.status for i in w.invoices] == ["matched", "mismatch"]
    assert "duplicate" in w.emails_to("manager@x.co")[-1][2].lower()


def test_a_thank_you_reply_confirms_the_order_and_is_not_treated_as_an_invoice(w):
    case_id = _ordered_case(w)
    outcome = w.reply(case_id, "Acme", "Thanks, we have received your order.",
                      subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert outcome == "po_confirmed" and w.invoices == []
    assert "po.confirmed" in w.event_types(case_id)


def test_a_question_about_the_order_is_logged_not_treated_as_an_invoice(w):
    case_id = _ordered_case(w)
    outcome = w.reply(case_id, "Acme", "Where should we deliver it?", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert outcome == "vendor_reply" and w.invoices == [] and "vendor.replied" in w.event_types(case_id)


def test_a_stranger_cannot_inject_a_quote(w):
    case_id = w.submit("50 cameras")
    outcome = case_pipeline.ingest_quote_email({
        "from_email": "scammer@evil.com", "subject": f"RE: [OA-{case_id}] Request for quotation",
        "body": "Total Rs 1. Delivery 1 days."})
    assert outcome == "not_invited" and w.quotes == []


# ---------- path 7: the pause switch ----------

def test_pause_holds_new_work_and_resume_catches_up(w, monkeypatch):
    from app.core import automation
    monkeypatch.setattr(automation, "is_paused", lambda: True)

    case_id = w.submit("50 cameras")
    assert w.stage(case_id) == "sourcing_needed" and w.sent == []        # request accepted, nothing sent
    assert "automation.held" in w.event_types(case_id)
    w.tick()
    assert w.sent == []                                                  # still idle while paused

    monkeypatch.setattr(automation, "is_paused", lambda: False)
    w.tick()
    assert w.stage(case_id) == "sourcing_needed" and w.sent == []        # too fresh: not raced
    w.cases[case_id].updated_at = now() - timedelta(minutes=30)
    w.tick()
    assert w.stage(case_id) == "awaiting_quotes" and len(w.sent) == 3    # caught up after resume


def test_resume_also_raises_an_order_held_while_paused(w, monkeypatch):
    from app.core import automation
    case_id = w.submit("50 cameras")
    monkeypatch.setattr(automation, "is_paused", lambda: True)
    source_paused_quotes = {"Acme": QUOTE_42K, "Globex": QUOTE_45K}
    for vendor, text in source_paused_quotes.items():
        w.reply(case_id, vendor, text)
    w.expire_quote_deadline(case_id)
    monkeypatch.setattr(automation, "is_paused", lambda: False)
    w.tick()                                       # ranks and approves
    monkeypatch.setattr(automation, "is_paused", lambda: True)
    # (an approval that lands while paused would stay at 'approved' with no order)
    w.cases[case_id].stage = "approved"
    w.pos.pop(case_id, None)
    case_pipeline._issue_purchase_order_safely(case_id)
    assert case_id not in w.pos and "automation.held" in w.event_types(case_id)

    monkeypatch.setattr(automation, "is_paused", lambda: False)
    w.cases[case_id].updated_at = now() - timedelta(minutes=30)
    w.tick()
    assert w.pos[case_id].status == "sent" and w.stage(case_id) == "po_issued"
