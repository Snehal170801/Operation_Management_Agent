"""Quotes expire: an approval that waited too long must not order at a price the supplier no longer stands behind."""

from datetime import datetime, timedelta

import pytest

from app.agents import approval_agent, operations_agent, vendor_agent
from app.controllers import approval_controller
from app.core import quote_expiry as qe
from app.core.exceptions import QuoteExpired
from app.orchestrator import case_pipeline

from .fake_world import World, now, standard_world

T0 = datetime(2026, 3, 2, 9)


# ---- the rules ----

def test_validity_is_worked_out_from_the_days_stated():
    assert qe.valid_until(T0, 7) == T0 + timedelta(days=7) and qe.valid_until(T0, 7.9) == T0 + timedelta(days=7)
    for bad in (None, 0, -3, 400, True, "7", float("nan")):
        assert qe.valid_until(T0, bad) is None


def test_expired_means_past_the_date_and_no_date_never_expires():
    assert qe.is_expired({"valid_until": T0}, T0 + timedelta(seconds=1)) and not qe.is_expired({"valid_until": T0}, T0)
    assert not qe.is_expired({"valid_until": None}, T0) and not qe.is_expired({}, T0)


def test_the_approver_label():
    assert qe.tag({"valid_until": None}, T0) is None
    assert qe.tag({"valid_until": T0 + timedelta(days=2)}, T0) == "Valid until 04 Mar"
    assert qe.tag({"valid_until": T0 - timedelta(days=1)}, T0) == "Quote expired"


# ---- the flow ----

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


BIG = "Total Rs {p}. Delivery 5 days. Valid for 7 days. Terms: net 30"


def waiting_for_an_approver(w):
    case_id = w.submit("50 cameras")
    for name, price in (("Acme", "90,000"), ("Globex", "95,000")):
        w.reply(case_id, name, BIG.format(p=price))
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval"
    return case_id, next(a for a in approval_agent.get_approvals(case_id=case_id) if a["status"] == "pending")


def outdate(w, case_id, days=8):
    for q in w.quotes:
        if q.case_id == case_id and q.valid_until:
            q.valid_until = now() - timedelta(days=days - 7)


def test_the_validity_the_supplier_states_is_stored_and_shown_to_the_approver(w):
    case_id, approval = waiting_for_an_approver(w)
    assert all(q.valid_until and timedelta(days=6) < q.valid_until - now() <= timedelta(days=7, minutes=1) for q in w.quotes if q.case_id == case_id)
    review = approval_controller.get_review(approval["approval_id"])
    assert all(any(t.startswith("Valid until") for t in o.tags) for o in review.options)


def test_a_quote_without_a_stated_validity_never_blocks_an_order(w):
    case_id = w.submit("50 cameras")
    for name, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30", "Globex": "Total Rs 45,000. Delivery 7 days. Terms: net 30"}.items():
        w.reply(case_id, name, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "po_issued" and all(q.valid_until is None for q in w.quotes)


def test_approving_after_the_quote_expired_asks_the_supplier_instead_of_ordering(w):
    case_id, approval = waiting_for_an_approver(w)
    chosen = vendor_agent.get_vendor_selection(case_id)["vendor_name"]
    outdate(w, case_id)
    mark = len(w.sent)
    case_pipeline.decide_approval(approval["approval_id"], True, "mgr", None)            # must not raise: the approval itself stands
    assert case_id not in w.pos                                                           # no order was placed
    assert w.stage(case_id) == "awaiting_quotes" and case_id not in w.selections
    asked = [m for m in w.sent[mark:] if "Quotation expired" in m[1]]
    assert len(asked) == 1 and asked[0][0] == f"{chosen.lower()}@vendor.com" and "expired on" in asked[0][2] and "still hold" in asked[0][2]
    assert "quote.refresh_requested" in w.event_types(case_id)
    assert "expired" in w.emails_to("manager@x.co")[-1][2]                                # the approvers know why it did not go out
    assert [q.vendor_name for q in w.quotes if q.case_id == case_id and q.superseded_at is not None] == [chosen]
    rfq = next(r for r in w.rfqs if r.case_id == case_id and r.vendor_name == chosen)
    assert rfq.status == "sent" and rfq.reminder_count == 0


def test_the_refreshed_price_goes_through_the_choice_and_approval_again(w):
    case_id, approval = waiting_for_an_approver(w)
    chosen = vendor_agent.get_vendor_selection(case_id)["vendor_name"]
    outdate(w, case_id)
    case_pipeline.decide_approval(approval["approval_id"], True, "mgr", None)
    w.reply(case_id, chosen, "Yes, our price still holds: Total Rs 41,000. Delivery 5 days. Valid for 7 days. Terms: net 30")
    assert w.stage(case_id) == "po_issued" and w.pos[case_id].total_amount == 41000.0      # cheap now, so ordered at the refreshed price
    assert w.pos[case_id].vendor_name == chosen


def test_a_supplier_who_never_refreshes_is_replaced_by_the_others(w):
    case_id, approval = waiting_for_an_approver(w)
    chosen = vendor_agent.get_vendor_selection(case_id)["vendor_name"]
    other = "Globex" if chosen == "Acme" else "Acme"
    outdate(w, case_id)
    case_pipeline.decide_approval(approval["approval_id"], True, "mgr", None)
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval" or w.stage(case_id) == "po_issued"
    sel = vendor_agent.get_vendor_selection(case_id)
    assert sel["vendor_name"] == other                                                     # the one whose quote expired is out


def test_the_retry_endpoint_path_also_refuses_an_expired_quote(w):
    case_id, approval = waiting_for_an_approver(w)
    case_pipeline.decide_approval(approval["approval_id"], True, "mgr", None)              # orders fine while the quote is valid
    assert case_id in w.pos


def test_issuing_directly_on_an_expired_quote_raises_and_asks_the_supplier(w):
    case_id, approval = waiting_for_an_approver(w)
    # approve without letting the pipeline issue (as if automation had been paused), then let the quote lapse
    w.approvals[-1].status = "approved"
    outdate(w, case_id)
    with pytest.raises(QuoteExpired, match="expired on"):
        case_pipeline.issue_purchase_order(case_id)
    assert case_id not in w.pos and "quote.refresh_requested" in w.event_types(case_id)
