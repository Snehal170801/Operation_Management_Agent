"""After an approver rejects the offers, the request can go back out for new quotes instead of ending."""

import pytest

from app.agents import approval_agent, operations_agent, vendor_agent
from app.core import resource_policy
from app.core.config import settings
from app.core.exceptions import InvalidInput
from app.orchestrator import case_pipeline

from .fake_world import standard_world


@pytest.fixture
def world(monkeypatch):
    w = standard_world(monkeypatch)
    w.teach("8 steel racks", [{"description": "Steel rack", "quantity": 8}])
    return w


def quote(w, case, who, price):
    w.reply(case, who, f"Hello, 8 steel racks total Rs {price}, delivery 5 days, payment 30 days.")


def big_offers(w):
    """A request whose offers are all above the automatic limit, so it waits for a person."""
    case = w.submit("8 steel racks")
    for name, price in (("Acme", 72000), ("Globex", 74000), ("Initech", 76000)):
        quote(w, case, name, price)
    assert w.stage(case) == "awaiting_approval"
    return case, next(a for a in approval_agent.get_approvals(case_id=case) if a["status"] == "pending")


# ---- the rules ----

def test_rounds_are_counted_from_rejections_that_asked_again():
    events = [{"event_type": "approval.rejected", "payload": {"re_sourcing": True}},
              {"event_type": "approval.rejected", "payload": {}},
              {"event_type": "approval.approved", "payload": {}}]
    assert resource_policy.rounds_used(events) == 1 and resource_policy.round_number(events) == 2
    assert resource_policy.can_resource(events, 2) and not resource_policy.can_resource(events, 1)
    assert not resource_policy.can_resource([], 0)


# ---- the flow ----

def test_rejecting_and_asking_again_sends_the_request_back_out(world):
    case, approval = big_offers(world)
    mark = len(world.sent)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", "too dear", re_source=True)

    assert world.stage(case) == "awaiting_quotes" and world.cases[case].status == "open"       # not closed
    assert approval_agent.get_approval(approval["approval_id"])["status"] == "rejected"        # the decision is on record
    asked = [m for m in world.sent[mark:] if "Request for quotation" in m[1]]
    assert sorted(m[0] for m in asked) == ["acme@vendor.com", "globex@vendor.com", "initech@vendor.com"]
    assert all("fresh quotations" in m[2] for m in asked)
    assert vendor_agent.get_quotes(case) == []                                                  # the old offers no longer count
    assert len(vendor_agent.get_quotes(case, include_superseded=True)) == 3                     # but they are kept
    assert case not in world.selections
    assert all(r.status == "sent" and r.reminder_count == 0 for r in world.rfqs if r.case_id == case)
    restarted = next(e for e in world.events[case] if e.event_type == "sourcing.restarted")
    assert restarted.payload["round"] == 2 and len(restarted.payload["vendors"]) == 3


def test_the_selected_supplier_can_be_left_out_of_the_new_round(world):
    case, approval = big_offers(world)
    selected = vendor_agent.get_vendor_selection(case)["vendor_name"]
    mark = len(world.sent)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", None, re_source=True, skip_selected=True)
    asked = {m[0] for m in world.sent[mark:] if "Request for quotation" in m[1]}
    assert f"{selected.lower()}@vendor.com" not in asked and len(asked) == 2
    assert selected not in [r.vendor_name for r in world.rfqs if r.case_id == case]            # nobody waits on them


def test_new_quotes_go_through_the_normal_steps_again(world):
    case, approval = big_offers(world)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", "too dear", re_source=True)
    quote(world, case, "Acme", 40000)
    assert world.stage(case) == "awaiting_quotes"                                              # still waiting for the others
    quote(world, case, "Globex", 41000)
    quote(world, case, "Initech", 42000)
    assert world.stage(case) == "po_issued"                                                     # cheap enough now, ordered on its own
    assert vendor_agent.get_vendor_selection(case)["vendor_name"] in ("Acme", "Globex")
    assert [e.event_type for e in world.events[case]].count("approval.auto_approved") == 1


def test_silence_in_the_new_round_is_handled_like_any_round(world):
    case, approval = big_offers(world)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", None, re_source=True)
    world.expire_quote_deadline(case)
    assert case_pipeline.advance_sourcing(case) == "stalled"                                   # no new quote at all: a person is told
    assert world.stage(case) == "sourcing_stalled"


def test_asking_again_is_limited(world, monkeypatch):
    monkeypatch.setattr(settings, "RESOURCE_MAX_ROUNDS", 1)
    case, approval = big_offers(world)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", None, re_source=True)
    for name in ("Acme", "Globex", "Initech"):
        quote(world, case, name, 90000)
    second = next(a for a in approval_agent.get_approvals(case_id=case) if a["status"] == "pending")
    with pytest.raises(InvalidInput, match="limit"):
        case_pipeline.decide_approval(second["approval_id"], False, "mgr", None, re_source=True)
    assert approval_agent.get_approval(second["approval_id"])["status"] == "pending"           # nothing was changed
    assert world.stage(case) == "awaiting_approval"
    case_pipeline.decide_approval(second["approval_id"], False, "mgr", "no more", re_source=False)   # it can still be rejected for good
    assert world.stage(case) == "rejected" and world.cases[case].status == "closed"


def test_switching_it_off_means_a_rejection_is_final(world, monkeypatch):
    monkeypatch.setattr(settings, "RESOURCE_MAX_ROUNDS", 0)
    case, approval = big_offers(world)
    with pytest.raises(InvalidInput):
        case_pipeline.decide_approval(approval["approval_id"], False, "mgr", None, re_source=True)
    assert world.stage(case) == "awaiting_approval"


def test_a_plain_rejection_and_an_approval_are_unchanged(world):
    case, approval = big_offers(world)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", "no")
    assert world.stage(case) == "rejected" and world.cases[case].status == "closed"
    assert "sourcing.restarted" not in world.event_types(case)
    case2, approval2 = big_offers(world)
    case_pipeline.decide_approval(approval2["approval_id"], True, "mgr", None, re_source=True)   # asking again makes no sense on approval
    assert world.stage(case2) == "po_issued" and "sourcing.restarted" not in world.event_types(case2)


def test_the_requester_sees_only_safe_wording(world):
    from app.core.agent_flow import build_flow
    from app.core import case_access
    case, approval = big_offers(world)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", "too dear", re_source=True)
    events = operations_agent.get_case_events(case)
    texts = " ".join(a["text"] for a in build_flow(operations_agent.get_case_status(case), events, "requester", world_now())["activity"])
    assert "Offers turned down" in texts and "too dear" not in texts and "mgr" not in texts
    assert "sourcing.restarted" in case_access._REQUESTER_VISIBLE_EVENTS


def world_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_the_approver_is_told_which_round_it_is_and_whether_asking_again_is_allowed(world):
    from app.controllers import approval_controller
    case, approval = big_offers(world)
    first = approval_controller.get_review(approval["approval_id"])
    assert (first.round, first.earlier_note, first.can_ask_again) == (1, None, True)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", "too dear", re_source=True)
    for name in ("Acme", "Globex", "Initech"):
        quote(world, case, name, 90000)
    second_approval = next(a for a in approval_agent.get_approvals(case_id=case) if a["status"] == "pending")
    second = approval_controller.get_review(second_approval["approval_id"])
    assert second.round == 2 and second.earlier_note == "too dear" and second.can_ask_again is True
    assert len(second.options) == 3 and all(o.price == 90000 for o in second.options)                 # only this round's offers
    assert approval_controller.get_review(approval["approval_id"]).can_ask_again is False             # a decided approval cannot be re-asked


def test_the_staff_view_keeps_the_turned_down_offers_and_the_replay_shows_them_as_they_were(world):
    from app.core.agent_info import as_of, build_agent_info
    case, approval = big_offers(world)
    mid = world_now()
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", "too dear", re_source=True)
    quote(world, case, "Acme", 40000)
    data = {"case": operations_agent.get_case_status(case), "events": operations_agent.get_case_events(case),
            "rfqs": vendor_agent.get_rfqs(case), "quotes": vendor_agent.get_quotes(case), "earlier_quotes": vendor_agent.get_earlier_quotes(case),
            "vendors": {v["vendor_id"]: v for v in vendor_agent.get_all_vendors()}, "selection": None}
    assert len(data["quotes"]) == 1 and len(data["earlier_quotes"]) == 3
    titles = [s["title"] for s in build_agent_info("vendor", data, True)["sections"]]
    assert any(t.startswith("Earlier offers") for t in titles)
    # (the test clock is too coarse to order these, so give them clear times)
    from datetime import timedelta
    for n, q in enumerate(data["earlier_quotes"]):
        q["created_at"], q["superseded_at"] = mid - timedelta(hours=3), mid + timedelta(hours=1)
    data["quotes"][0]["created_at"] = mid + timedelta(hours=2)
    before = as_of(data, mid)                                           # before the turn-down: the three offers were the current ones
    assert len(before["quotes"]) == 3 and before["earlier_quotes"] == []
    after = as_of(data, mid + timedelta(hours=3))                       # after: the new offer counts, the three are kept as earlier
    assert len(after["quotes"]) == 1 and len(after["earlier_quotes"]) == 3
