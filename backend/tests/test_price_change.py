"""A supplier changes the price after quoting or after the order: a dearer price never slips through unseen."""

from datetime import datetime, timedelta

import pytest

from app.agents import approval_agent, operations_agent, purchase_order_agent, vendor_agent
from app.controllers import approval_controller
from app.core import price_change as pc
from app.core import quotes as qr
from app.core.exceptions import VendorNotApproved
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, QUOTE_90K, source

T0 = datetime(2026, 3, 2, 9)


# ---- the rules ----

def test_a_price_is_only_a_price_if_it_is_a_usable_amount():
    assert pc.clean_price("1,20,000") == 120000.0 and pc.clean_price("₹ 30000") == 30000.0 and pc.clean_price(30000) == 30000.0
    for bad in (None, "", "abc", 0, -5, True, float("nan"), float("inf")):
        assert pc.clean_price(bad) is None


def test_what_to_do_with_a_new_price():
    assert pc.assess(100000, 100000, 2)["action"] == "confirm"
    assert pc.assess(100000, 101500, 2) == {"action": "confirm", "pct": 1.5, "new_total": 101500.0}        # within the tolerance
    assert pc.assess(100000, 115000, 2) == {"action": "higher", "pct": 15.0, "new_total": 115000.0}
    assert pc.assess(100000, 90000, 2)["action"] == "lower"
    assert pc.assess(100000, 5_000_000, 2)["action"] == "unclear"                                        # ten times more: a misreading
    assert pc.assess(100000, 5000, 2)["action"] == "unclear"
    assert pc.assess(None, 90000, 2)["action"] == "unclear" and pc.assess(0, 90000, 2)["action"] == "unclear"
    assert pc.assess(100000, "x", 2)["action"] == "unclear"


def q(vendor, price, minutes):
    return {"vendor_id": vendor, "price": price, "created_at": T0 + timedelta(minutes=minutes)}


def test_the_latest_quote_from_a_supplier_counts():
    out = qr.latest_per_vendor([q("A", 50, 0), q("B", 40, 1), q("A", 45, 2), q("B", None, 3)])
    assert [(x["vendor_id"], x["price"]) for x in out] == [("A", 45), ("B", 40)]     # B's later quote had no price, so the earlier priced one stands
    assert qr.vendor_count([q("A", 1, 0), q("A", 2, 1), q("B", 3, 2)]) == 2


# ---- revised quotes before the order ----

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def test_a_revised_quote_replaces_the_earlier_price_when_everyone_has_replied(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", QUOTE_90K)
    w.reply(case_id, "Acme", "Total Rs 40,000. Delivery 7 days. Terms: net 30")          # Acme changes its mind
    w.reply(case_id, "Globex", QUOTE_45K)
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "po_issued"
    assert w.pos[case_id].total_amount == 40000.0                                           # the order is at the latest price, not the first


def test_one_supplier_quoting_three_times_is_still_one_quote(w):
    case_id = w.submit("50 cameras")
    for price in (42000, 41000, 40000):
        w.reply(case_id, "Acme", f"Total Rs {price}. Delivery 7 days. Terms: net 30")
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval"                                          # needs two different suppliers to approve automatically
    pending = next(a for a in w.approvals if a.status == "pending")
    assert "Only 1 quote" in pending.reasons                            # (stored as text)


def test_a_revised_price_while_waiting_for_an_approver_makes_the_choice_again(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_90K, "Globex": "Total Rs 95,000. Delivery 7 days. Terms: net 30"})
    assert w.stage(case_id) == "awaiting_approval"
    old = next(a for a in w.approvals if a.status == "pending")
    mark = len(w.events[case_id])
    assert w.reply(case_id, "Acme", "Sorry, we can do it for Total Rs 41,000. Delivery 7 days. Terms: net 30") == "quote_revised"
    assert old.status == "superseded"                                                         # the old question is withdrawn
    revised = next(e for e in w.events[case_id][mark:] if e.event_type == "quote.revised")
    assert (revised.payload["old_price"], revised.payload["new_price"]) == (90000.0, 41000.0)
    assert w.stage(case_id) == "po_issued" and w.pos[case_id].total_amount == 41000.0         # cheap enough now: ordered automatically


def test_an_unreadable_revision_is_logged_and_changes_nothing(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_90K, "Globex": "Total Rs 95,000. Delivery 7 days. Terms: net 30"})
    assert w.reply(case_id, "Acme", "") == "empty" and w.stage(case_id) == "awaiting_approval"


def test_an_older_approval_cannot_release_an_order_after_the_choice_changed(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_90K, "Globex": "Total Rs 95,000. Delivery 7 days. Terms: net 30"})
    first = next(a for a in w.approvals if a.status == "pending")
    case_pipeline.decide_approval(first.approval_id, False, "mgr", "ask again", re_source=True)
    for name in ("Acme", "Globex"):
        w.reply(case_id, name, "Total Rs 99,000. Delivery 7 days. Terms: net 30")
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval" and case_id not in w.pos
    with pytest.raises(VendorNotApproved):
        case_pipeline.issue_purchase_order(case_id)


# ---- a price change after the order ----

def ordered(w) -> str:
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def reply(w, case_id, text):
    return w.reply(case_id, w.pos[case_id].vendor_name, text, subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")


def pending_price(w, case_id):
    return next((a for a in approval_agent.get_approvals(case_id=case_id) if a["approval_type"] == "price_change" and a["status"] == "pending"), None)


def test_a_higher_price_goes_to_an_approver_and_changes_nothing_yet(w):
    case_id = ordered(w)
    mark = len(w.sent)
    assert reply(w, case_id, "Steel went up, the price is now Rs 55,000.") == "po_price_change"
    po = w.pos[case_id]
    assert po.total_amount == 42000.0 and po.acknowledged_at is None and "55,000" in po.vendor_issue          # untouched; supplier reminders stop
    approval = pending_price(w, case_id)
    assert approval and "up 31" in approval["reasons"][0] and "₹55,000" in approval["reasons"][0] and "₹42,000" in approval["reasons"][0]
    assert any("approval" in m[1].lower() for m in w.sent[mark:])                                          # the approvers were told
    assert w.stage(case_id) == "po_issued"                                                                  # the case itself did not move
    assert "po.price_change_proposed" in w.event_types(case_id)


def test_the_approver_sees_the_agreed_and_the_asked_price(w):
    case_id = ordered(w)
    reply(w, case_id, "Steel went up, the price is now Rs 55,000.")
    review = approval_controller.get_review(pending_price(w, case_id)["approval_id"])
    assert review.kind == "price_change" and review.price_change.agreed_total == 42000.0 and review.price_change.new_total == 55000.0
    assert review.price_change.vendor_name == w.pos[case_id].vendor_name and "55,000" in review.price_change.reply_text and review.options == []


def test_accepting_the_higher_price_updates_the_order_and_tells_the_supplier(w):
    case_id = ordered(w)
    reply(w, case_id, "Steel went up, the price is now Rs 55,000.")
    mark = len(w.sent)
    case_pipeline.decide_approval(pending_price(w, case_id)["approval_id"], True, "mgr", "market moved")
    po = w.pos[case_id]
    assert po.total_amount == 55000.0 and po.vendor_issue is None and po.acknowledged_at is not None
    mail = w.sent[mark]
    assert "revised price accepted" in mail[1] and "55,000.00" in mail[2] and mail[0] == po.vendor_email
    assert w.stage(case_id) == "po_issued" and w.cases[case_id].status == "open"                          # the case carries on
    assert "po.price_change_accepted" in w.event_types(case_id)
    # the invoice for the new price now matches
    case_pipeline.confirm_delivery(case_id, "recv", None)
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 55,000. 50 x CCTV camera.")
    assert [i.status for i in w.invoices] == ["matched"] and w.cases[case_id].status == "closed"


def test_refusing_the_higher_price_asks_the_supplier_to_honour_the_agreed_one(w):
    case_id = ordered(w)
    reply(w, case_id, "Steel went up, the price is now Rs 55,000.")
    mark = len(w.sent)
    case_pipeline.decide_approval(pending_price(w, case_id)["approval_id"], False, "mgr", "no")
    po = w.pos[case_id]
    assert po.total_amount == 42000.0 and "refused" in po.vendor_issue
    assert "not accepted" in w.sent[mark][1] and "42,000.00" in w.sent[mark][2]
    assert w.stage(case_id) == "po_issued" and w.cases[case_id].status == "open"                          # a refusal does not close the case
    assert "po.price_change_rejected" in w.event_types(case_id)
    # the supplier then agrees to the original price
    assert reply(w, case_id, "OK, we confirm the order at the agreed price and will deliver.") == "po_confirmed"
    assert w.pos[case_id].vendor_issue is None and w.pos[case_id].acknowledged_at is not None


def test_a_lower_price_is_simply_taken(w):
    case_id = ordered(w)
    mark = len(w.sent)
    assert reply(w, case_id, "Good news, the price is now Rs 40,000.") == "po_price_lowered"
    assert w.pos[case_id].total_amount == 40000.0 and pending_price(w, case_id) is None
    assert "po.price_lowered" in w.event_types(case_id) and w.sent[mark:] == []


def test_a_restated_agreed_price_is_just_a_confirmation(w):
    case_id = ordered(w)
    assert reply(w, case_id, "We confirm. The price is now Rs 42,000 as quoted.") == "po_confirmed"
    assert w.pos[case_id].acknowledged_at is not None and pending_price(w, case_id) is None


def test_a_wild_number_is_a_problem_to_read_not_a_price(w):
    case_id = ordered(w)
    assert reply(w, case_id, "The price is now Rs 9,00,00,000.") == "po_problem"                         # ten times or more: a misreading
    assert w.pos[case_id].total_amount == 42000.0 and pending_price(w, case_id) is None and w.pos[case_id].vendor_issue


def test_asking_again_replaces_the_open_question(w):
    case_id = ordered(w)
    reply(w, case_id, "The price is now Rs 55,000.")
    first = pending_price(w, case_id)
    reply(w, case_id, "Sorry, the price is now Rs 58,000 actually.")
    second = pending_price(w, case_id)
    assert second["approval_id"] != first["approval_id"] and "58,000" in second["reasons"][0]
    assert [a.status for a in w.approvals if a.approval_id == first["approval_id"]] == ["superseded"]


def test_after_the_goods_arrive_a_price_message_is_not_a_price_change(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert reply(w, case_id, "The price is now Rs 55,000.") != "po_price_change" and pending_price(w, case_id) is None
    assert w.pos[case_id].total_amount == 42000.0


def test_the_tolerance_can_be_changed(w, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "PRICE_CHANGE_TOLERANCE_PCT", 50)
    case_id = ordered(w)
    assert reply(w, case_id, "The price is now Rs 55,000.") != "po_price_change"                          # 31% is within 50%
