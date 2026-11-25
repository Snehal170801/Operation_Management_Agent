"""Cancelling or changing a request, before and after the order goes to the supplier."""

from datetime import datetime, timedelta

import pytest

from app.agents import operations_agent, purchase_agent, purchase_order_agent, vendor_agent
from app.core import change_policy as cp
from app.core.exceptions import InvalidInput
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, QUOTE_90K, source

T0 = datetime(2026, 3, 2, 9)
ITEMS = [{"description": "Steel rack", "quantity": 8}, {"description": "Bracket", "quantity": 10}]


# ---- the rules ----

def case(status="open"):
    return {"status": status}


def po(**o):
    return {"status": "sent", "cancel_requested_at": None, **o}


def test_phase_follows_how_far_the_order_got():
    assert cp.phase(case("closed"), None, None) == "closed"
    assert cp.phase(case(), None, None) == "before_order"
    assert cp.phase(case(), po(status="issued"), None) == "before_order"            # created but never emailed
    assert cp.phase(case(), po(), {"delivery_status": "pending", "batches": []}) == "after_order"
    assert cp.phase(case(), po(cancel_requested_at=T0), None) == "cancelling"
    assert cp.phase(case(), po(), {"delivery_status": "pending", "batches": [{}]}) == "delivered"     # part of it came
    assert cp.phase(case(), po(), {"delivery_status": "delivered", "batches": []}) == "delivered"


def test_options_say_what_is_allowed():
    o = cp.options(case(), po(), {"delivery_status": "pending", "batches": []}, [])
    assert o["can_cancel"] and o["can_change"] and o["pending_change"] is None
    pending = [{"event_type": cp.CHANGE_REQUESTED, "payload": {"changes": [{"item": "x", "from": 1, "to": 2}], "by": "ann"}, "created_at": T0}]
    o = cp.options(case(), po(), {"delivery_status": "pending", "batches": []}, pending)
    assert o["can_cancel"] and not o["can_change"] and o["pending_change"]["by"] == "ann"
    assert not cp.options(case(), po(cancel_requested_at=T0), None, [])["can_cancel"]
    assert not cp.options(case(), po(), {"delivery_status": "pending", "batches": [{}]}, [])["can_cancel"]


def test_a_handled_change_is_no_longer_pending():
    ev = [{"event_type": cp.CHANGE_REQUESTED, "payload": {"changes": []}, "created_at": T0}, {"event_type": cp.CHANGE_HANDLED, "payload": {}, "created_at": T0 + timedelta(hours=1)}]
    assert cp.pending_change(ev) is None


def test_plan_changes_checks_every_quantity():
    assert cp.plan_changes(ITEMS, {"steel  RACK": 10}) == [{"item": "Steel rack", "from": 8, "to": 10}]
    assert cp.plan_changes(ITEMS, {"Steel rack": 8, "Bracket": 4}) == [{"item": "Bracket", "from": 10, "to": 4}]     # unchanged lines are ignored
    for bad in ({"Chair": 3}, {"Steel rack": 0}, {"Steel rack": -2}, {"Steel rack": 1.5}, {"Steel rack": True}, {"Steel rack": 8}, {}, {"Steel rack": 10 ** 7}):
        with pytest.raises(cp.BadChange):
            cp.plan_changes(ITEMS, bad)


# ---- the flow ----

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def asked(w, since=0):
    return [m for m in w.sent[since:] if "Request for quotation" in m[1]]


def ordered(w) -> str:
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def reply(w, case_id, text):
    return w.reply(case_id, w.pos[case_id].vendor_name, text, subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")


def test_cancelling_before_any_order_ends_the_request_and_tells_the_suppliers(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", QUOTE_42K)
    mark = len(w.sent)
    out = case_pipeline.cancel_case(case_id, "ann", "no longer needed")
    assert out["outcome"] == "cancelled" and sorted(out["suppliers_told"]) == ["Acme", "Globex", "Initech"]
    told = w.sent[mark:]
    assert len(told) == 3 and all("WITHDRAWN" in m[1] and "no longer need" in m[2] for m in told)
    assert all("no longer needed" not in m[2] for m in told)                      # the requester's reason stays internal
    assert w.stage(case_id) == "cancelled" and w.cases[case_id].status == "closed"
    assert all(r.status == "withdrawn" for r in w.rfqs if r.case_id == case_id)
    ev = w.event_types(case_id)
    assert "case.cancelled" in ev and "rfq.withdrawn" in ev
    assert w.reply(case_id, "Globex", QUOTE_45K) == "not_accepting"                 # a late quote is not picked up


def test_a_waiting_approval_is_withdrawn_when_the_request_is_cancelled(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_90K, "Globex": "Total Rs 95,000. Delivery 7 days. Terms: net 30"})
    assert w.stage(case_id) == "awaiting_approval"
    case_pipeline.cancel_case(case_id, "ann", None)
    assert [a.status for a in w.approvals if a.case_id == case_id] == ["superseded"]


def test_cancelling_after_the_order_asks_the_supplier_and_waits(w):
    case_id = ordered(w)
    mark = len(w.sent)
    out = case_pipeline.cancel_case(case_id, "ann", "project dropped")
    assert out["outcome"] == "cancelling" and w.stage(case_id) == "cancel_pending" and w.cases[case_id].status == "open"
    mail = w.sent[mark]
    assert "CANCELLATION" in mail[1] and "project dropped" in mail[2] and mail[0] == w.pos[case_id].vendor_email
    assert w.pos[case_id].status == "sent" and w.pos[case_id].cancel_requested_at is not None       # still live until they agree
    w.pos[case_id].expected_delivery_date = datetime.now().date() - timedelta(days=3)
    assert case_pipeline.track_deliveries() == {"chased": 0, "escalated": 0}                        # no chasing while we wait
    assert case_pipeline.track_po_confirmations() == {"chased": 0, "escalated": 0}
    with pytest.raises(InvalidInput):
        case_pipeline.cancel_case(case_id, "ann", None)                               # already asked


def test_the_supplier_agreeing_closes_the_case_as_cancelled(w):
    case_id = ordered(w)
    case_pipeline.cancel_case(case_id, "ann", None)
    assert reply(w, case_id, "No problem, the order is cancelled.") == "po_cancelled"
    assert w.pos[case_id].status == "cancelled" and w.stage(case_id) == "cancelled" and w.cases[case_id].status == "closed"
    assert "po.cancelled" in w.event_types(case_id)


def test_the_supplier_refusing_alerts_the_po_team_who_can_settle_or_carry_on(w):
    case_id = ordered(w)
    case_pipeline.cancel_case(case_id, "ann", None)
    assert reply(w, case_id, "Sorry, it has already shipped and cannot be cancelled.") == "po_cancel_refused"
    assert [a["kind"] for a in purchase_order_agent.get_confirmation_alerts()] == ["cancel_refused"]
    assert "cannot be cancelled" in w.emails_to("manager@x.co")[-1][2]
    case_pipeline.resolve_cancellation(case_id, "carry_on", "po", "goods are on the way")
    assert w.stage(case_id) == "po_issued" and w.pos[case_id].cancel_requested_at is None and purchase_order_agent.get_confirmation_alerts() == []
    assert "po.cancel_withdrawn" in w.event_types(case_id)


def test_a_person_can_settle_a_cancellation_by_phone(w):
    case_id = ordered(w)
    case_pipeline.cancel_case(case_id, "ann", None)
    case_pipeline.resolve_cancellation(case_id, "settled", "po", "rang them")
    assert w.stage(case_id) == "cancelled" and w.pos[case_id].status == "cancelled"
    with pytest.raises(InvalidInput):
        case_pipeline.resolve_cancellation(case_id, "settled", "po", None)             # nothing waiting any more


def test_a_silent_supplier_is_asked_again_then_the_po_team_is_told_once(w):
    case_id = ordered(w)
    case_pipeline.cancel_case(case_id, "ann", None)
    p = w.pos[case_id]

    def age():
        p.cancel_requested_at -= timedelta(hours=25)
        if p.last_cancel_chase_at:
            p.last_cancel_chase_at -= timedelta(hours=25)
    assert case_pipeline.track_cancellations() == {"chased": 0, "escalated": 0}
    for _ in range(2):
        age()
        assert case_pipeline.track_cancellations()["chased"] == 1
    age()
    assert case_pipeline.track_cancellations() == {"chased": 0, "escalated": 1}
    assert [a["kind"] for a in purchase_order_agent.get_confirmation_alerts()] == ["cancel_overdue"]
    age()
    assert case_pipeline.track_cancellations() == {"chased": 0, "escalated": 0}


def test_an_unrelated_reply_while_cancelling_is_just_logged(w):
    case_id = ordered(w)
    case_pipeline.cancel_case(case_id, "ann", None)
    assert reply(w, case_id, "Which warehouse is this for?") == "vendor_reply" and w.stage(case_id) == "cancel_pending"


def test_too_late_once_goods_have_arrived(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 10})
    with pytest.raises(InvalidInput, match="goods have already arrived"):
        case_pipeline.cancel_case(case_id, "ann", None)
    with pytest.raises(InvalidInput, match="goods have already arrived"):
        case_pipeline.change_case(case_id, "ann", {"CCTV camera": 5}, None)


def test_changing_the_quantity_before_the_order_asks_the_suppliers_again(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", QUOTE_42K)
    mark = len(w.sent)
    out = case_pipeline.change_case(case_id, "ann", {"CCTV camera": 60}, "a few more")
    assert out["outcome"] == "changed" and out["changes"] == [{"item": "CCTV camera", "from": 50, "to": 60}]
    assert purchase_agent.get_purchase_request(case_id)["items"][0]["quantity"] == 60
    assert w.stage(case_id) == "awaiting_quotes"
    mails = asked(w, mark)
    assert len(mails) == 3 and all("CCTV camera x 60" in m[2] and "fresh quotations" in m[2] for m in mails)
    assert vendor_agent.get_quotes(case_id) == [] and len(vendor_agent.get_earlier_quotes(case_id)) == 1      # the old price was for 50
    assert "request.changed" in w.event_types(case_id)


def test_changing_to_a_quantity_that_is_in_stock_fills_it_from_the_store_room(w):
    w.add_stock("Widget", 5)
    w.teach("8 widgets", [{"description": "Widget", "quantity": 8}])
    case_id = w.submit("8 widgets")
    assert w.stage(case_id) == "awaiting_quotes"
    mark = len(w.sent)
    out = case_pipeline.change_case(case_id, "ann", {"Widget": 4}, None)
    assert out["outcome"] == "filled_from_stock" and w.stage(case_id) == "fulfilled_from_stock" and w.stock["widget"].quantity_available == 1
    assert len([m for m in w.sent[mark:] if "WITHDRAWN" in m[1]]) == 3


def test_a_pending_approval_is_withdrawn_when_the_quantity_changes(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_90K, "Globex": "Total Rs 95,000. Delivery 7 days. Terms: net 30"})
    case_pipeline.change_case(case_id, "ann", {"CCTV camera": 40}, None)
    assert [a.status for a in w.approvals if a.case_id == case_id] == ["superseded"] and w.stage(case_id) == "awaiting_quotes"


def test_bad_changes_are_refused_without_touching_anything(w):
    case_id = w.submit("50 cameras")
    for bad in ({"Chair": 3}, {"CCTV camera": 0}, {"CCTV camera": 50}):
        with pytest.raises(InvalidInput):
            case_pipeline.change_case(case_id, "ann", bad, None)
    assert purchase_agent.get_purchase_request(case_id)["items"][0]["quantity"] == 50 and "request.changed" not in w.event_types(case_id)


def test_a_change_after_the_order_goes_to_the_po_desk(w):
    case_id = ordered(w)
    mark = len(w.sent)
    out = case_pipeline.change_case(case_id, "ann", {"CCTV camera": 60}, "need more")
    assert out["outcome"] == "passed_to_po_desk"
    assert all(m[0] == "manager@x.co" for m in w.sent[mark:])                                       # the supplier is not emailed by itself
    assert purchase_agent.get_purchase_request(case_id)["items"][0]["quantity"] == 50                # nothing changes until agreed
    assert cp.pending_change(operations_agent.get_case_events(case_id))["changes"][0]["to"] == 60
    with pytest.raises(InvalidInput, match="already waiting"):
        case_pipeline.change_case(case_id, "ann", {"CCTV camera": 70}, None)

    case_pipeline.resolve_change(case_id, "amended", "po", 50400.0, "supplier agreed, new total")
    assert purchase_agent.get_purchase_request(case_id)["items"][0]["quantity"] == 60
    order = purchase_order_agent.get_purchase_order(case_id)
    assert order["items"][0]["quantity"] == 60 and order["total_amount"] == 50400.0
    assert cp.pending_change(operations_agent.get_case_events(case_id)) is None


def test_a_declined_change_leaves_the_order_as_it_was(w):
    case_id = ordered(w)
    case_pipeline.change_case(case_id, "ann", {"CCTV camera": 60}, None)
    case_pipeline.resolve_change(case_id, "declined", "po", None, "supplier cannot")
    assert purchase_order_agent.get_purchase_order(case_id)["items"][0]["quantity"] == 50
    assert cp.pending_change(operations_agent.get_case_events(case_id)) is None
    with pytest.raises(InvalidInput):
        case_pipeline.resolve_change(case_id, "declined", "po", None, None)


def test_cancelled_cases_are_shown_as_cancelled_not_rejected(w):
    from app.core.agent_flow import build_flow
    case_id = w.submit("50 cameras")
    case_pipeline.cancel_case(case_id, "ann", None)
    flow = build_flow(operations_agent.get_case_status(case_id), operations_agent.get_case_events(case_id), "requester", datetime.utcnow())
    assert flow["outcome"] == "cancelled" and flow["headline"] == "This request was cancelled."
    assert [a["state"] for a in flow["agents"]].count("stopped") == 1
