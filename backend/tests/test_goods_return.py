"""Returning faulty goods and waiting for a replacement or a credit note: tracked, visible, and nothing owed is ever changed automatically."""

import pytest

from app.agents import delivery_agent
from app.core import goods_issues as gi
from app.core.exceptions import InvalidInput
from app.orchestrator import case_pipeline

from .fake_world import standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source
from .test_restock import ordered_reorder


# ---- the rules ---------------------------------------------------------------------------------------------------------------------------

def issue(**kw):
    return {"status": "open", "return_status": None, "replacement_status": None, "vendor_name": "Acme", "po_number": "PO-1001",
            "items": [{"description": "CCTV camera", "quantity": 5}], "credit_amount": 500.0, "credit_note_number": None, **kw}


def test_progress_says_where_a_problem_is():
    assert gi.progress(issue()) == "reported"
    assert gi.progress(issue(return_status="returned")) == "returned"
    assert gi.progress(issue(return_status="returned", replacement_status="expected")) == "replacement_expected"
    assert gi.progress(issue(status="resolved")) == "resolved"


def test_each_step_is_only_allowed_when_it_makes_sense():
    gi.check_can_return(issue())
    gi.check_can_expect_replacement(issue())
    gi.check_can_receive_replacement(issue(replacement_status="expected"))
    for check, bad in ((gi.check_can_return, issue(return_status="returned")), (gi.check_can_return, issue(status="resolved")),
                       (gi.check_can_expect_replacement, issue(replacement_status="expected")), (gi.check_can_expect_replacement, issue(status="resolved")),
                       (gi.check_can_receive_replacement, issue()), (gi.check_can_receive_replacement, issue(replacement_status="received")),
                       (gi.check_can_receive_replacement, issue(status="resolved", replacement_status="expected"))):
        with pytest.raises(gi.BadIssue):
            check(bad)


def test_references_are_short_plain_text():
    assert gi.clean_ref("  RMA   123 ") == "RMA 123" and gi.clean_ref("") is None and gi.clean_ref(None) is None
    with pytest.raises(gi.BadIssue):
        gi.clean_ref("x" * 101)


def test_the_messages_say_what_is_needed():
    notice = gi.return_notice("Acme", "PO-1001", issue()["items"], "RMA-7")
    assert "CCTV camera × 5" in notice and "RMA-7" in notice and "credit note" in notice
    credit = gi.credit_message(issue(credit_note_number="CN-9"))
    assert "500.00" in credit and "CN-9" in credit and "by hand" in credit and "Nothing you owe was changed automatically" in credit


# ---- through the pipeline ----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    return standard_world(monkeypatch)


def ordered(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    case_pipeline.confirm_delivery(case_id, "recv", None)
    return case_id


def reported(w):
    case_id = ordered(w)
    return case_id, case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, "crushed", "recv")


def test_returning_the_goods_is_recorded_the_supplier_is_told_and_the_problem_stays_open(w):
    case_id, i = reported(w)
    mark = len(w.sent)
    out = case_pipeline.return_goods(i["issue_id"], " RMA-7 ", "recv")
    assert out["return_status"] == "returned" and out["return_ref"] == "RMA-7" and out["returned_by"] == "recv" and out["status"] == "open"
    mail = next(m for m in w.sent[mark:] if "being returned" in m[1])
    assert mail[0] == w.pos[case_id].vendor_email and "RMA-7" in mail[2] and "CCTV camera × 5" in mail[2]
    assert "goods.returned" in w.event_types(case_id)


def test_returning_twice_or_after_the_problem_closed_is_refused(w):
    case_id, i = reported(w)
    case_pipeline.return_goods(i["issue_id"], None, "recv")
    with pytest.raises(InvalidInput, match="already been marked as returned"):
        case_pipeline.return_goods(i["issue_id"], None, "recv")
    case_pipeline.resolve_goods_issue(i["issue_id"], "accepted", None, None, "recv")
    with pytest.raises(InvalidInput, match="already been closed"):
        case_pipeline.return_goods(i["issue_id"], None, "recv")
    assert w.event_types(case_id).count("goods.returned") == 1


def test_a_failing_return_notice_never_stops_the_return_being_recorded(w, monkeypatch):
    case_id, i = reported(w)
    monkeypatch.setattr(delivery_agent.email_client, "send_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    out = case_pipeline.return_goods(i["issue_id"], None, "recv")
    assert out["return_status"] == "returned"
    assert next(e for e in w.events[case_id] if e.event_type == "goods.returned").payload["supplier_told"] is False


def test_a_promised_replacement_keeps_payment_held_and_stops_the_reminders(w):
    case_id, i = reported(w)
    out = case_pipeline.expect_goods_replacement(i["issue_id"], "recv")
    assert out["replacement_status"] == "expected" and out["status"] == "open" and out["supplier_replied_at"]
    w.reply(case_id, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert w.invoices[0].status == "on_hold" and w.cases[case_id].status == "open"          # still held
    with pytest.raises(InvalidInput, match="already expected"):
        case_pipeline.expect_goods_replacement(i["issue_id"], "recv")


def test_the_replacement_arriving_ends_the_problem_releases_the_invoice_and_closes_the_case(w):
    case_id, i = reported(w)
    case_pipeline.return_goods(i["issue_id"], "RMA-7", "recv")
    case_pipeline.expect_goods_replacement(i["issue_id"], "recv")
    w.reply(case_id, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    out = case_pipeline.receive_goods_replacement(i["issue_id"], "all five came", "recv")
    assert out["status"] == "resolved" and out["resolution"] == "replaced" and out["replacement_status"] == "received"
    assert w.invoices[0].status == "matched" and w.cases[case_id].status == "closed"
    assert {"goods.replacement_expected", "goods.replacement_received", "goods.issue_resolved"} <= set(w.event_types(case_id))


def test_a_replacement_cannot_arrive_that_was_never_promised_or_twice(w):
    case_id, i = reported(w)
    with pytest.raises(InvalidInput, match="No replacement is expected"):
        case_pipeline.receive_goods_replacement(i["issue_id"], None, "recv")
    case_pipeline.expect_goods_replacement(i["issue_id"], "recv")
    case_pipeline.receive_goods_replacement(i["issue_id"], None, "recv")
    with pytest.raises(InvalidInput):
        case_pipeline.receive_goods_replacement(i["issue_id"], None, "recv")


def test_a_credit_is_logged_for_accounts_to_apply_by_hand_with_its_number_and_nothing_is_paid(w):
    case_id, i = reported(w)
    mark = len(w.emails_to("manager@x.co"))
    out = case_pipeline.resolve_goods_issue(i["issue_id"], "credit", 5000.0, "agreed on the phone", "recv", " CN-9 ")
    assert out["credit_amount"] == 5000.0 and out["credit_note_number"] == "CN-9"
    mails = w.emails_to("manager@x.co")[mark:]
    assert any("credit of 5,000.00 (credit note CN-9)" in m[2] and "apply it by hand" in m[2] for m in mails)
    logged = next(e for e in w.events[case_id] if e.event_type == "goods.credit_logged")
    assert logged.payload["credit_amount"] == 5000.0 and logged.payload["credit_note_number"] == "CN-9"
    assert not [e for e in w.event_types(case_id) if "paid" in e or "payment" in e]


def test_a_credit_without_a_number_still_tells_accounts_and_a_replacement_does_not(w):
    case_id, i = reported(w)
    case_pipeline.resolve_goods_issue(i["issue_id"], "credit", 100.0, None, "recv")
    assert "goods.credit_logged" in w.event_types(case_id)
    other, j = reported(w)
    case_pipeline.resolve_goods_issue(j["issue_id"], "replaced", None, None, "recv")
    assert "goods.credit_logged" not in w.event_types(other)


def test_a_bad_credit_note_number_is_refused_and_nothing_closes(w):
    case_id, i = reported(w)
    with pytest.raises(InvalidInput):
        case_pipeline.resolve_goods_issue(i["issue_id"], "credit", 100.0, None, "recv", "x" * 150)
    assert delivery_agent.get_issue(i["issue_id"])["status"] == "open"


def test_a_failing_accounts_alert_never_undoes_the_closed_problem(w, monkeypatch):
    case_id, i = reported(w)
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    out = case_pipeline.resolve_goods_issue(i["issue_id"], "credit", 100.0, None, "recv", "CN-1")
    assert out["status"] == "resolved"


def test_for_a_reorder_the_stock_comes_off_when_reported_and_goes_back_when_the_replacement_arrives(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None)
    before = w.stock["cctv camera"].quantity_available
    i = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    assert w.stock["cctv camera"].quantity_available == before - 5
    case_pipeline.return_goods(i["issue_id"], "RMA-1", "recv")
    assert w.stock["cctv camera"].quantity_available == before - 5                        # returning changes nothing on the shelf: they were already off
    case_pipeline.expect_goods_replacement(i["issue_id"], "recv")
    case_pipeline.receive_goods_replacement(i["issue_id"], None, "recv")
    assert w.stock["cctv camera"].quantity_available == before                            # the replacements go back on


def test_a_credit_leaves_reorder_stock_off(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None)
    before = w.stock["cctv camera"].quantity_available
    i = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    case_pipeline.return_goods(i["issue_id"], None, "recv")
    case_pipeline.resolve_goods_issue(i["issue_id"], "credit", 900.0, None, "recv", "CN-2")
    assert w.stock["cctv camera"].quantity_available == before - 5


def test_my_work_says_where_each_problem_is():
    from datetime import datetime
    from app.core.my_work import build_my_work
    base = {"issue_id": "i", "case_id": "c" * 36, "po_number": "PO-1", "vendor_name": "Acme", "items": [{"description": "Cam", "quantity": 2}], "kind": "damaged",
            "reported_at": datetime(2026, 1, 1), "escalated_at": None, "supplier_replied_at": None}
    case = {"case_id": "c" * 36, "case_number": "REQ-1", "status": "open", "items_summary": "cams", "stage": "po_issued", "requester_id": "r"}

    def text(**extra):
        work = build_my_work("recv", lambda p: p == "delivery:confirm", approvals=[], cases=[case], deliveries=[], invoices=[], stock=[], now=datetime(2026, 1, 2),
                             goods_issues=[{**base, **extra}])
        return work["queues"][0]["items"][0]["detail"]
    assert "A replacement is promised" in text(replacement_status="expected")
    assert "sent back" in text(return_status="returned")
    assert "Waiting for the supplier to put it right" in text()
