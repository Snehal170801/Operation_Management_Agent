"""The supplier must confirm the purchase order: asked again if silent, a person told if they never answer or raise a problem."""

from datetime import datetime, timedelta, timezone

import pytest

from app.agents import operations_agent, purchase_order_agent
from app.core.agent_flow import build_flow, po_needs_person
from app.core.config import settings
from app.core.po_confirm_policy import next_confirm_action
from app.orchestrator import case_pipeline

from .fake_world import World, now, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

T0 = datetime(2026, 3, 2, 9)


def po(**over):
    return {"acknowledged_at": None, "confirm_escalated_at": None, "vendor_issue": None, "sent_at": T0, "last_confirm_chase_at": None,
            "confirm_chase_count": 0, **over}


# ---- the rules ----

def test_nothing_happens_before_the_wait_is_over_and_a_confirmed_order_is_left_alone():
    assert next_confirm_action(po(), T0 + timedelta(hours=23), 24, 2) == "wait"
    assert next_confirm_action(po(), T0 + timedelta(hours=24), 24, 2) == "chase"
    assert next_confirm_action(po(acknowledged_at=T0), T0 + timedelta(days=9), 24, 2) == "wait"
    assert next_confirm_action(po(sent_at=None), T0 + timedelta(days=9), 24, 2) == "wait"


def test_chases_are_a_day_apart_and_then_a_person_is_told_once():
    later = lambda hours: T0 + timedelta(hours=hours)
    assert next_confirm_action(po(confirm_chase_count=1, last_confirm_chase_at=later(24)), later(47), 24, 2) == "wait"
    assert next_confirm_action(po(confirm_chase_count=1, last_confirm_chase_at=later(24)), later(48), 24, 2) == "chase"
    assert next_confirm_action(po(confirm_chase_count=2, last_confirm_chase_at=later(48)), later(72), 24, 2) == "escalate"
    assert next_confirm_action(po(confirm_chase_count=2, confirm_escalated_at=later(72)), later(200), 24, 2) == "wait"
    assert next_confirm_action(po(vendor_issue="cannot supply"), later(200), 24, 2) == "wait"       # a person already has it


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


def age(w, case_id, hours):
    p = w.pos[case_id]
    p.sent_at = p.sent_at - timedelta(hours=hours)
    if p.last_confirm_chase_at:
        p.last_confirm_chase_at -= timedelta(hours=hours)


def test_a_supplier_who_replies_to_confirm_is_recorded_and_never_chased(w):
    case_id = ordered(w)
    assert reply(w, case_id, "Confirmed, we will deliver in 7 days.") == "po_confirmed"
    p = w.pos[case_id]
    assert p.acknowledged_at is not None and "@vendor.com" in p.acknowledged_by
    assert "po.confirmed" in w.event_types(case_id)
    age(w, case_id, 100)
    assert case_pipeline.track_po_confirmations() == {"chased": 0, "escalated": 0}


def test_a_silent_supplier_is_asked_twice_then_the_po_team_is_told_once(w):
    case_id = ordered(w)
    mark = len(w.sent)
    assert case_pipeline.track_po_confirmations() == {"chased": 0, "escalated": 0}                # too soon

    age(w, case_id, 25)
    assert case_pipeline.track_po_confirmations()["chased"] == 1
    first = w.sent[mark:]
    assert len(first) == 1 and "please confirm" in first[0][1] and f"[OA-{case_id}]" in first[0][1] and w.pos[case_id].vendor_email == first[0][0]

    assert case_pipeline.track_po_confirmations() == {"chased": 0, "escalated": 0}                # not again straight away
    age(w, case_id, 25)
    assert case_pipeline.track_po_confirmations()["chased"] == 1
    assert w.pos[case_id].confirm_chase_count == 2

    mark = len(w.sent)
    age(w, case_id, 25)
    assert case_pipeline.track_po_confirmations() == {"chased": 0, "escalated": 1}                # no third reminder: a person is told
    alert = w.emails_to("manager@x.co")[-1]
    assert "has not confirmed" in alert[2] and "2 reminder" in alert[2]
    assert "po.confirmation_overdue" in w.event_types(case_id)
    age(w, case_id, 100)
    assert case_pipeline.track_po_confirmations() == {"chased": 0, "escalated": 0}                # told only once


def test_a_late_confirmation_after_the_alert_clears_it(w):
    case_id = ordered(w)
    for _ in range(3):
        age(w, case_id, 25)
        case_pipeline.track_po_confirmations()
    assert [a["kind"] for a in purchase_order_agent.get_confirmation_alerts()] == ["overdue"]
    assert reply(w, case_id, "Order received and accepted, apologies for the delay.") == "po_confirmed"
    assert purchase_order_agent.get_confirmation_alerts() == []


def test_an_invoice_from_the_supplier_also_counts_as_confirming(w):
    case_id = ordered(w)
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    assert w.pos[case_id].acknowledged_at is not None
    assert "po.confirmed" in w.event_types(case_id)


def test_a_problem_reply_alerts_the_po_team_and_stops_the_reminders(w):
    case_id = ordered(w)
    mark = len(w.sent)
    assert reply(w, case_id, "Sorry, we cannot deliver 50 by then.") == "po_problem"
    p = w.pos[case_id]
    assert p.vendor_issue and p.acknowledged_at is None
    assert "po.vendor_problem" in w.event_types(case_id)
    assert "raised a problem" in w.emails_to("manager@x.co")[-1][2]
    assert [a["kind"] for a in purchase_order_agent.get_confirmation_alerts()] == ["problem"]
    age(w, case_id, 100)
    assert case_pipeline.track_po_confirmations() == {"chased": 0, "escalated": 0}               # a person has it, so no more nagging
    assert len(w.sent) == mark + 1


def test_a_person_confirms_it_another_way_or_closes_the_problem(w):
    case_id = ordered(w)
    reply(w, case_id, "Sorry, we cannot deliver 50 by then.")
    case_pipeline.confirm_purchase_order(case_id, "poguy", "Rang them, new date agreed")
    p = w.pos[case_id]
    assert p.acknowledged_at is not None and p.vendor_issue is None and p.acknowledged_by == "poguy"
    assert purchase_order_agent.get_confirmation_alerts() == []
    ev = [e for e in operations_agent.get_case_events(case_id) if e.get("event_type") == "po.confirmed"][-1]
    assert ev["payload"]["via"] == "person" and ev["payload"]["by"] == "poguy"

    # a problem raised after confirming can also be closed
    reply(w, case_id, "Sorry, the price has gone up.")
    assert w.pos[case_id].vendor_issue
    case_pipeline.confirm_purchase_order(case_id, "poguy", "Agreed to keep the price")
    assert w.pos[case_id].vendor_issue is None and "po.problem_resolved" in w.event_types(case_id)


def test_a_question_is_just_logged(w):
    case_id = ordered(w)
    assert reply(w, case_id, "Where should we deliver it?") == "vendor_reply"
    assert w.pos[case_id].acknowledged_at is None and w.pos[case_id].vendor_issue is None


def test_the_people_and_the_screens_reflect_it(w):
    from app.core.my_work import build_my_work
    case_id = ordered(w)
    for _ in range(3):
        age(w, case_id, 25)
        case_pipeline.track_po_confirmations()
    events = operations_agent.get_case_events(case_id)
    assert po_needs_person(events)
    case = operations_agent.get_case_status(case_id)
    staff = build_flow(case, events, "staff", datetime.now(timezone.utc).replace(tzinfo=None))
    po_agent = next(a for a in staff["agents"] if a["key"] == "po")
    assert po_agent["state"] == "needs_person" and "not confirmed" in po_agent["label"]
    requester = build_flow(case, events, "requester", datetime.now(timezone.utc).replace(tzinfo=None))
    assert "has not confirmed" not in next(a for a in requester["agents"] if a["key"] == "po")["label"]      # no detail for the requester

    work = build_my_work("po", lambda p: p == "po:manage", approvals=[], cases=[{**case, "case_id": case_id, "items_summary": "50 cameras", "updated_at": now()}],
                         deliveries=[], invoices=[], stock=[], now=now(), po_alerts=purchase_order_agent.get_confirmation_alerts())
    item = work["queues"][0]["items"][0]
    assert item["urgent"] and "has not confirmed PO-1001 after 2 reminder" in item["detail"]

    case_pipeline.confirm_purchase_order(case_id, "poguy", None)
    assert not po_needs_person(operations_agent.get_case_events(case_id))


def test_goods_arriving_counts_as_the_supplier_having_the_order(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert w.pos[case_id].acknowledged_at is not None and purchase_order_agent.get_confirmation_alerts() == []
    ev = next(e for e in operations_agent.get_case_events(case_id) if e["event_type"] == "po.confirmed")
    assert ev["payload"]["via"] == "delivery"


def test_the_times_can_be_changed_in_configure(w, monkeypatch):
    monkeypatch.setattr(settings, "PO_CONFIRM_HOURS", 2)
    monkeypatch.setattr(settings, "PO_CONFIRM_MAX_CHASES", 1)
    case_id = ordered(w)
    age(w, case_id, 3)
    assert case_pipeline.track_po_confirmations()["chased"] == 1
    age(w, case_id, 3)
    assert case_pipeline.track_po_confirmations()["escalated"] == 1
