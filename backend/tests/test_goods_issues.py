"""Wrong or damaged goods: recorded, the supplier asked to fix it, payment held, a credit comes off what may be billed."""

from datetime import timedelta

import pytest

from app.agents import delivery_agent, operations_agent
from app.core import goods_issues as gi
from app.core.agent_flow import build_flow, goods_issue_open
from app.core.exceptions import InvalidInput
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

ORDERED = [{"description": "Steel rack", "quantity": 8}, {"description": "Bracket", "quantity": 10}]
ARRIVED = {"steel rack": 8, "bracket": 6}


# ---- the rules ----

def test_a_report_names_what_is_affected_from_what_actually_arrived():
    items, text = gi.validate_report(ORDERED, ARRIVED, "damaged", {"steel  RACK": 2}, "  dented  ")
    assert items == [{"description": "Steel rack", "quantity": 2}] and text == "dented"
    everything, _ = gi.validate_report(ORDERED, ARRIVED, "wrong_item", None, None)
    assert everything == [{"description": "Steel rack", "quantity": 8}, {"description": "Bracket", "quantity": 6}]


@pytest.mark.parametrize("kind, items, desc", [
    ("exploded", None, None), ("damaged", {"Chair": 1}, None), ("damaged", {"Steel rack": 0}, None),
    ("damaged", {"Bracket": 7}, None),                      # only 6 arrived
    ("damaged", {"Steel rack": 1.5}, None), ("damaged", {}, None), ("other", None, "  "),
])
def test_nonsense_reports_are_refused(kind, items, desc):
    with pytest.raises(gi.BadIssue):
        gi.validate_report(ORDERED, ARRIVED, kind, items, desc)


def test_nothing_can_be_faulty_before_anything_arrived():
    with pytest.raises(gi.BadIssue, match="Nothing has been recorded as received"):
        gi.validate_report(ORDERED, {}, "damaged", None, None)


def test_how_a_problem_may_end():
    assert gi.validate_resolution("replaced", None, 1000) is None and gi.validate_resolution("accepted", 50, 1000) is None
    assert gi.validate_resolution("credit", 250.456, 1000) == 250.46
    for bad in (("credit", None), ("credit", 0), ("credit", -1), ("credit", True), ("credit", 2000), ("refunded", 5)):
        with pytest.raises(gi.BadIssue):
            gi.validate_resolution(bad[0], bad[1], 1000)


def test_only_resolved_credits_count():
    issues = [{"status": "resolved", "resolution": "credit", "credit_amount": 100.0}, {"status": "resolved", "resolution": "replaced", "credit_amount": None},
              {"status": "open", "resolution": None, "credit_amount": None}, {"status": "resolved", "resolution": "credit", "credit_amount": 50.5}]
    assert gi.credit_total(issues) == 150.5 and len(gi.open_issues(issues)) == 1


# ---- the flow ----

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def ordered(w) -> str:
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def reply(w, case_id, text):
    return w.reply(case_id, w.pos[case_id].vendor_name, text, subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")


def received(w, case_id):
    case_pipeline.confirm_delivery(case_id, "recv", None)


def test_reporting_a_problem_asks_the_supplier_holds_payment_and_alerts_receiving(w):
    case_id = ordered(w)
    received(w, case_id)
    mark = len(w.sent)
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, "boxes crushed", "recv")
    assert issue["status"] == "open" and issue["items"] == [{"description": "CCTV camera", "quantity": 5}] and issue["supplier_told_at"]
    mail = next(m for m in w.sent[mark:] if "goods problem" in m[1])
    assert mail[0] == w.pos[case_id].vendor_email and "CCTV camera × 5" in mail[2] and "boxes crushed" in mail[2] and "credit note" in mail[2]
    assert "reported a problem with the goods" in w.emails_to("manager@x.co")[-1][2]
    assert "goods.issue_reported" in w.event_types(case_id)
    assert goods_issue_open(operations_agent.get_case_events(case_id))


def test_an_invoice_that_matches_is_still_held_while_a_problem_is_open_and_the_case_does_not_close(w):
    case_id = ordered(w)
    received(w, case_id)
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    inv = w.invoices[0]
    assert inv.status == "on_hold" and "goods is still open" in inv.issues
    assert w.cases[case_id].status == "open"


def test_replacing_the_goods_releases_the_invoice_and_closes_the_case(w):
    case_id = ordered(w)
    received(w, case_id)
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    case_pipeline.resolve_goods_issue(issue["issue_id"], "replaced", None, "new ones arrived Tuesday", "recv")
    assert w.invoices[0].status == "matched" and w.cases[case_id].status == "closed"
    assert "goods.issue_resolved" in w.event_types(case_id)


def test_an_agreed_credit_comes_off_what_the_supplier_may_bill(w):
    case_id = ordered(w)
    received(w, case_id)
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    case_pipeline.resolve_goods_issue(issue["issue_id"], "credit", 4200.0, "10% credit note", "recv")
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")                 # the full amount: too much now
    assert w.invoices[0].status == "mismatch" and "37,800.00" in w.invoices[0].issues
    reply(w, case_id, "Invoice INV-8 for PO-1001. Total Rs 37,800. 50 x CCTV camera.")                 # the reduced amount matches
    assert w.invoices[1].status == "matched"


def test_a_reduced_invoice_sent_before_the_credit_is_recorded_waits_for_a_person(w):
    case_id = ordered(w)
    received(w, case_id)
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 37,800. 50 x CCTV camera.")
    assert w.invoices[0].status == "mismatch" and w.cases[case_id].status == "open"           # not auto-cleared: no credit has been agreed yet


def test_an_invoice_for_the_old_amount_that_was_held_is_flagged_once_a_credit_is_agreed(w):
    case_id = ordered(w)
    received(w, case_id)
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    case_pipeline.resolve_goods_issue(issue["issue_id"], "credit", 4200.0, None, "recv")
    assert w.invoices[0].status == "mismatch" and w.cases[case_id].status == "open"
    assert "does not match what is now owed" in w.emails_to("manager@x.co")[-1][2]


def test_accepting_the_goods_as_they_are_changes_nothing_owed(w):
    case_id = ordered(w)
    received(w, case_id)
    issue = case_pipeline.report_goods_issue(case_id, "not_as_described", None, "slightly different model", "recv")
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    case_pipeline.resolve_goods_issue(issue["issue_id"], "accepted", None, "fine for our use", "recv")
    assert w.invoices[0].status == "matched" and w.cases[case_id].status == "closed"


def test_a_closed_request_or_a_second_resolution_is_refused(w):
    case_id = ordered(w)
    with pytest.raises(InvalidInput, match="Nothing has been recorded as received"):
        case_pipeline.report_goods_issue(case_id, "damaged", None, None, "recv")             # nothing has arrived yet
    received(w, case_id)
    issue = case_pipeline.report_goods_issue(case_id, "other", None, "smells of smoke", "recv")
    case_pipeline.resolve_goods_issue(issue["issue_id"], "accepted", None, None, "recv")
    with pytest.raises(InvalidInput, match="already been closed"):
        case_pipeline.resolve_goods_issue(issue["issue_id"], "replaced", None, None, "recv")
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    assert w.cases[case_id].status == "closed"
    with pytest.raises(InvalidInput, match="already closed"):
        case_pipeline.report_goods_issue(case_id, "damaged", None, None, "recv")


def test_a_reply_about_the_faulty_goods_is_recorded_and_stops_the_chasing(w):
    case_id = ordered(w)
    received(w, case_id)
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    assert reply(w, case_id, "We will send five replacements next week.") == "goods_issue_reply"
    assert "goods.supplier_replied" in w.event_types(case_id) and w.issues[0].supplier_replied_at is not None
    w.issues[0].supplier_told_at -= timedelta(hours=100)
    assert case_pipeline.track_goods_issues() == {"chased": 0, "escalated": 0}


def test_a_silent_supplier_is_asked_twice_then_receiving_is_told_once(w):
    case_id = ordered(w)
    received(w, case_id)
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    issue = w.issues[0]

    def age():
        issue.supplier_told_at -= timedelta(hours=25)
        if issue.last_chased_at:
            issue.last_chased_at -= timedelta(hours=25)
    assert case_pipeline.track_goods_issues() == {"chased": 0, "escalated": 0}
    for _ in range(2):
        age()
        assert case_pipeline.track_goods_issues()["chased"] == 1
    age()
    assert case_pipeline.track_goods_issues() == {"chased": 0, "escalated": 1}
    assert "has not said how they will put right" in w.emails_to("manager@x.co")[-1][2]
    age()
    assert case_pipeline.track_goods_issues() == {"chased": 0, "escalated": 0}


def test_receivings_my_work_lists_it_and_the_delivery_agent_needs_a_person(w):
    from app.core.my_work import build_my_work
    case_id = ordered(w)
    received(w, case_id)
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    cases = operations_agent.get_all_cases(None)
    work = build_my_work("recv", lambda p: p == "delivery:confirm", approvals=[], cases=cases, deliveries=[], invoices=[], stock=[],
                         now=w.cases[case_id].created_at, goods_issues=delivery_agent.get_open_issues())
    item = next(i for i in work["queues"][0]["items"] if i["id"].startswith("goods-issue:"))
    assert "CCTV camera × 5" in item["detail"] and "Waiting for the supplier" in item["detail"]
    events = operations_agent.get_case_events(case_id)
    flow = build_flow(operations_agent.get_case_status(case_id), events, "staff", w.cases[case_id].created_at)
    delivery = next(a for a in flow["agents"] if a["key"] == "delivery")
    assert delivery["state"] == "needs_person" and "problem with the goods" in delivery["label"]
    requester = build_flow(operations_agent.get_case_status(case_id), events, "requester", w.cases[case_id].created_at)
    assert "CCTV" not in next(a for a in requester["agents"] if a["key"] == "delivery")["label"]


def test_orders_without_problems_behave_exactly_as_before(w):
    case_id = ordered(w)
    received(w, case_id)
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    assert w.invoices[0].status == "matched" and w.cases[case_id].status == "closed" and w.issues == []
