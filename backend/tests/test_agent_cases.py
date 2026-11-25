"""The cases around the other agents: who can really approve, goods that arrive wrongly, stock given back on a cancellation, a user who left."""

import pytest

from app.core import agent_cases as ac, change_policy
from app.core.exceptions import InvalidInput
from app.orchestrator import case_pipeline

from .fake_world import standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source


@pytest.fixture
def w(monkeypatch):
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    return standard_world(monkeypatch)


def person(username, email="auto", role="u_x"):
    return {"username": username, "email": username + "@x.co" if email == "auto" else email, "role": role}


# ---- (a) approver cover: the rule ------------------------------------------------------------------------------------------------------------

def test_a_normal_approver_with_an_email_who_is_not_the_requester_is_cover():
    assert ac.approver_cover([person("asha")], "ravi")["reason"] is None


def test_nobody_with_the_right_or_no_email_or_only_the_requester_is_a_reason_to_tell_the_admins():
    assert "Nobody has the right" in ac.approver_cover([], "ravi")["reason"]
    assert "e-mail address" in ac.approver_cover([person("asha", email=None), person("bo", email="  ")], "ravi")["reason"]
    assert "nobody may approve their own" in ac.approver_cover([person("ravi")], "ravi")["reason"]
    assert ac.approver_cover([person("ravi"), person("asha")], "ravi")["reason"] is None              # someone else can: fine


def test_when_only_admins_can_be_asked_the_admins_are_told_they_are_the_only_cover():
    cover = ac.approver_cover([person("root", role="admin"), person("ravi")], "ravi")
    assert cover["reason"] and cover["eligible"][0]["username"] == "root"


# ---- (a) approver cover: through the pipeline ------------------------------------------------------------------------------------------------

def make_pending(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": "Total Rs 900,000 delivery 7 days", "Globex": "Total Rs 950,000 delivery 8 days"})     # over the automatic limit: a person must approve
    assert w.stage(case_id) == "awaiting_approval"
    return case_id


def test_with_no_approver_able_to_be_asked_the_case_says_so_and_the_admins_are_told_once(w):
    w.managers = []
    case_id = make_pending(w)
    assert w.event_types(case_id).count("approval.routed_to_admin") == 1
    assert case_pipeline.check_approver_cover(case_id, next(e.payload["approval_id"] for e in w.events[case_id] if e.event_type == "approval.routed_to_admin")) is True
    assert w.event_types(case_id).count("approval.routed_to_admin") == 1                                    # not repeated


def test_with_a_working_approver_nothing_is_routed(w):
    case_id = make_pending(w)
    assert "approval.routed_to_admin" not in w.event_types(case_id)


def test_the_cover_check_never_breaks_the_approval(w, monkeypatch):
    monkeypatch.setattr(case_pipeline.notification_agent, "approver_people", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    case_id = make_pending(w)
    assert w.stage(case_id) == "awaiting_approval"


# ---- (b) delivery -----------------------------------------------------------------------------------------------------------------------------

def ordered(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def test_the_over_delivery_rule_names_the_extra_and_ignores_ordinary_receipts():
    items = [{"description": "CCTV camera", "quantity": 50}]
    assert ac.over_delivery(items, {"CCTV camera": 20}, {"cctv camera": 20}) == [] and ac.over_delivery(items, {"CCTV camera": 20}, {"cctv camera": 15}) == []
    assert ac.over_delivery(items, {"CCTV camera": 20}, {"cctv camera": 25}) == [{"description": "CCTV camera", "owed": 20, "arrived": 25, "extra": 5}]
    assert ac.over_delivery(items, {"CCTV camera": 20}, None) == [] and ac.over_delivery(items, {"CCTV camera": 20}, {"Chair": 9}) == []
    assert ac.over_delivery(items, {"CCTV camera": 20}, {"CCTV camera": True}) == []
    assert "5 extra" in ac.over_delivery_text(ac.over_delivery(items, {"CCTV camera": 20}, {"CCTV camera": 25}))


def test_more_than_was_ordered_is_refused_but_flagged_to_receiving_and_accounts_once(w):
    case_id = ordered(w)
    with pytest.raises(InvalidInput):
        case_pipeline.confirm_delivery(case_id, "ravi@x.co", None, {"CCTV camera": 60})
    assert "delivery.over_delivered" in w.event_types(case_id) and w.pos[case_id].delivery_status == "pending"
    first = len([m for m in w.emails_to("manager@x.co") if "More arrived than was ordered" in m[2]])
    assert first == 2                                                                                     # Receiving and Accounts (the fake world has one manager for every team)
    with pytest.raises(InvalidInput):
        case_pipeline.confirm_delivery(case_id, "ravi@x.co", None, {"CCTV camera": 60})
    assert w.event_types(case_id).count("delivery.over_delivered") == 1                                    # the same extra is not announced twice


def test_receiving_exactly_what_is_owed_is_not_flagged_and_other_refusals_say_nothing_extra(w):
    case_id = ordered(w)
    with pytest.raises(InvalidInput):
        case_pipeline.confirm_delivery(case_id, "ravi@x.co", None, {"Chair": 1})                           # not on the order
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None, {"CCTV camera": 50})
    assert "delivery.over_delivered" not in w.event_types(case_id)


def test_goods_before_a_confirmation_the_supplier_ignored_are_logged_but_normal_deliveries_are_not(w):
    normal = ordered(w)
    case_pipeline.confirm_delivery(normal, "ravi@x.co", None)
    assert "delivery.before_confirmation" not in w.event_types(normal)
    silent = ordered(w)
    w.pos[silent].confirm_chase_count = 2
    case_pipeline.confirm_delivery(silent, "ravi@x.co", None)
    assert "delivery.before_confirmation" in w.event_types(silent) and w.stage(silent) == "delivered"


def test_a_failing_lookup_never_stops_goods_being_received(w, monkeypatch):
    case_id = ordered(w)
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "find_purchase_order", lambda c: (_ for _ in ()).throw(RuntimeError("db down")))
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    assert w.pos[case_id].delivery_status == "delivered"


# ---- (c) stock back on a cancellation ---------------------------------------------------------------------------------------------------------

def fulfilled_from_stock(w):
    w.teach("2 laptops please", [{"description": "Laptop", "quantity": 2}])
    case_id = w.submit("2 laptops please")
    assert w.stage(case_id) == "fulfilled_from_stock" and w.stock["laptop"].quantity_available == 98
    return case_id


def test_the_rule_reads_what_a_case_took_from_stock_and_nothing_once_it_went_back():
    checked = {"event_type": "stock.checked", "payload": {"sufficient": True, "checks": [{"stock_item": "Laptop", "requested": 2}, {"stock_item": None, "requested": 3}]}}
    assert ac.stock_taken([checked]) == {"Laptop": 2}
    assert ac.stock_taken([checked, {"event_type": "stock.returned"}]) == {}
    assert ac.stock_taken([{"event_type": "stock.checked", "payload": {"sufficient": False, "checks": [{"stock_item": "Laptop", "requested": 2}]}}]) == {}


def test_a_request_filled_from_stock_can_be_cancelled_and_the_stock_goes_back_with_a_history_entry_and_stores_is_told(w):
    case_id = fulfilled_from_stock(w)
    assert change_policy.options(case_pipeline.operations_agent.get_case_status(case_id), None, None, [])["can_cancel"]
    assert case_pipeline.cancel_case(case_id, "ravi@x.co", "not needed")["outcome"] == "cancelled"
    assert w.stock["laptop"].quantity_available == 100 and w.stage(case_id) == "cancelled"
    assert "stock.returned" in w.event_types(case_id) and [m for m in w.emails_to("manager@x.co") if "put back" in m[2].lower() or "Put back" in m[2]]
    assert any(r.reason == "cancelled_returned" and r.case_id == case_id for r in w.ledger)


def test_a_second_cancel_cannot_put_the_stock_back_twice(w):
    case_id = fulfilled_from_stock(w)
    case_pipeline.cancel_case(case_id, "ravi@x.co", None)
    with pytest.raises(InvalidInput):
        case_pipeline.cancel_case(case_id, "ravi@x.co", None)
    assert w.stock["laptop"].quantity_available == 100


def test_a_stock_item_that_no_longer_exists_is_reported_not_lost(w):
    case_id = fulfilled_from_stock(w)
    del w.stock["laptop"]
    case_pipeline.cancel_case(case_id, "ravi@x.co", None)
    returned = next(e for e in w.events[case_id] if e.event_type == "stock.returned")
    assert returned.payload["unmatched"] == {"Laptop": 2} and w.stage(case_id) == "cancelled"


def test_other_finished_requests_still_cannot_be_cancelled(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    w.reply(case_id, "Acme", "Invoice INV-1 for PO-1001. Total Rs 42,000. 50 x CCTV camera.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    assert w.stage(case_id) == "completed"
    with pytest.raises(InvalidInput):
        case_pipeline.cancel_case(case_id, "ravi@x.co", None)


# ---- (d) a user who has left -------------------------------------------------------------------------------------------------------------------

def test_the_rule_finds_only_their_open_requests():
    cases = [{"case_id": "a" * 36, "requester_id": "Ravi@x.co", "status": "open"}, {"case_id": "b" * 36, "requester_id": "ravi@x.co", "status": "closed"},
             {"case_id": "c" * 36, "requester_id": "other@x.co", "status": "open"}]
    assert [c["case_id"] for c in ac.owned_open_cases(cases, "ravi@x.co")] == ["a" * 36]
    assert "1 request" in ac.left_text("Ravi", ac.owned_open_cases(cases, "ravi@x.co"))


def test_when_a_user_leaves_each_open_request_says_so_and_the_admins_get_one_email(w):
    mine = [w.submit("50 cameras", requester="ravi@x.co"), w.submit("50 cameras", requester="ravi@x.co")]
    other = w.submit("50 cameras", requester="other@x.co")
    before = len(w.emails_to("manager@x.co"))
    assert case_pipeline.handle_user_left("ravi@x.co", "Ravi")["cases"] == 2
    assert all("case.owner_left" in w.event_types(c) for c in mine) and "case.owner_left" not in w.event_types(other)
    assert len(w.emails_to("manager@x.co")) == before + 1 and "can no longer sign in" in w.emails_to("manager@x.co")[-1][2]


def test_a_user_with_no_open_requests_costs_nothing_and_a_failure_never_blocks_the_admin(w, monkeypatch):
    assert case_pipeline.handle_user_left("nobody@x.co") == {"cases": 0, "approvals": 0}
    monkeypatch.setattr(case_pipeline.operations_agent, "get_all_cases", lambda *a: (_ for _ in ()).throw(RuntimeError("db down")))
    assert case_pipeline.handle_user_left("ravi@x.co") == {"cases": 0, "approvals": 0}


def test_when_the_last_approver_leaves_the_pending_approval_is_routed_to_the_admins(w):
    case_id = make_pending(w)
    assert "approval.routed_to_admin" not in w.event_types(case_id)
    w.managers = []
    assert case_pipeline.handle_user_left("asha@x.co")["approvals"] == 1
    assert "approval.routed_to_admin" in w.event_types(case_id)


# ---- stock cancel is for staff only; links of a user who left -------------------------------------------------------------------------------

def test_a_requester_cannot_cancel_a_request_filled_from_stock_but_stores_can(w, monkeypatch):
    from app.controllers import case_change_controller
    from app.core.exceptions import Forbidden
    from app.models.auth_schemas import CurrentUser
    case_id = fulfilled_from_stock(w)
    monkeypatch.setattr(case_change_controller.access, "has_permission", lambda role, permission: False)
    requester = CurrentUser(user_id="9", username="ravi@x.co", role="u_requester")
    with pytest.raises(Forbidden, match="contact Stores"):
        case_change_controller.cancel(case_id, "not needed", requester)
    assert w.stock["laptop"].quantity_available == 98 and w.stage(case_id) == "fulfilled_from_stock"        # nothing happened
    monkeypatch.setattr(case_change_controller.access, "has_permission", lambda role, permission: permission == "stock:write")
    monkeypatch.setattr(case_change_controller.audit, "record", lambda *a, **k: None)
    assert case_change_controller.cancel(case_id, "stores did it", CurrentUser(user_id="2", username="stores", role="u_stores")).outcome == "cancelled"
    assert w.stock["laptop"].quantity_available == 100


def test_a_requester_can_still_cancel_an_ordinary_open_request(w, monkeypatch):
    from app.controllers import case_change_controller
    from app.models.auth_schemas import CurrentUser
    case_id = w.submit("50 cameras", requester="ravi@x.co")
    monkeypatch.setattr(case_change_controller.access, "has_permission", lambda role, permission: False)
    monkeypatch.setattr(case_change_controller.audit, "record", lambda *a, **k: None)
    assert case_change_controller.cancel(case_id, None, CurrentUser(user_id="9", username="ravi@x.co", role="u_requester")).outcome == "cancelled"


def test_a_deleted_approver_cannot_use_a_link_and_the_refusal_leaves_a_note_and_no_decision(w, monkeypatch):
    from types import SimpleNamespace
    from app.controllers import decision_controller
    from app.core import access
    from app.core.exceptions import LinkProblem
    from app.repositories import role_repository, user_repository
    from app.agents import approval_agent
    manager = "00000000-0000-0000-0000-000000000000"
    people = {manager: SimpleNamespace(user_id=manager, username="mgr@x.co", display_name="Mgr", role="manager", is_active=True, email="manager@x.co")}
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {"manager": {"approvals:write"}, "admin": {"approvals:write"}})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: people.get(str(uid)))
    access.invalidate()
    from .test_email_approval import big_order, links_in
    case_id = big_order(w)
    token = links_in(w)["approve"]
    del people[manager]                                                                     # deleted
    with pytest.raises(LinkProblem) as e:
        decision_controller.decide(token, "approve", None, "10.0.0.5")
    assert e.value.key == "person" and "no longer approve" in str(e.value)
    assert approval_agent.get_approvals("pending", case_id) and w.stage(case_id) == "awaiting_approval"      # nothing was decided
    assert "approval.link_refused" in w.event_types(case_id)
    count = w.event_types(case_id).count("approval.link_refused")
    with pytest.raises(LinkProblem):
        decision_controller.get_info(token)                                                 # just opening the page leaves no extra note
    assert w.event_types(case_id).count("approval.link_refused") == count


def test_when_a_user_leaves_their_unused_links_are_revoked_and_other_peoples_are_not(w):
    case_id = make_pending(w)
    from app.agents import approval_link_agent
    approval_id = next(e.payload["approval_id"] for e in w.events[case_id] if e.event_type == "approval.routed_to_admin") if False else w.approvals[0].approval_id
    approval_link_agent.create_link(approval_id, "user-a")
    approval_link_agent.create_link(approval_id, "user-b")
    case_pipeline.handle_user_left("a@x.co", "A", user_id="user-a")
    mine = [l for l in w.links if l.user_id == "user-a"]
    assert mine and all(l.revoked_at for l in mine)
    assert not any(l.revoked_at for l in w.links if l.user_id == "user-b")


def test_a_failure_revoking_links_never_blocks_the_rest(w, monkeypatch):
    monkeypatch.setattr(case_pipeline.approval_link_agent, "revoke_user_links", lambda uid: (_ for _ in ()).throw(RuntimeError("db down")))
    w.submit("50 cameras", requester="ravi@x.co")
    assert case_pipeline.handle_user_left("ravi@x.co", "Ravi", user_id="u")["cases"] == 1


def test_the_options_hide_cancel_from_a_requester_on_a_from_stock_request_but_not_from_stores_or_on_other_requests(w, monkeypatch):
    from app.controllers import case_change_controller as cc
    from app.models.auth_schemas import CurrentUser
    case_id = fulfilled_from_stock(w)
    requester = CurrentUser(user_id="9", username="ravi@x.co", role="u_requester")
    stores = CurrentUser(user_id="2", username="stores", role="u_stores")
    monkeypatch.setattr(cc.access, "has_permission", lambda role, permission: role == "u_stores" and permission == "stock:write")
    mine = cc.get_options(case_id, requester)
    assert mine.phase == "from_stock" and mine.can_cancel is False and "contact Stores" in mine.note
    assert cc.get_options(case_id, stores).can_cancel is True
    open_case = w.submit("50 cameras", requester="ravi@x.co")
    assert cc.get_options(open_case, requester).can_cancel is True                      # an ordinary open request: unchanged


def test_a_stranger_still_gets_not_found_from_the_options_of_a_from_stock_request(w, monkeypatch):
    from app.controllers import case_change_controller as cc
    from app.core.exceptions import CaseNotFound
    from app.models.auth_schemas import CurrentUser
    case_id = fulfilled_from_stock(w)
    monkeypatch.setattr(cc.access, "has_permission", lambda role, permission: False)
    with pytest.raises(CaseNotFound):
        cc.get_options(case_id, CurrentUser(user_id="8", username="other@x.co", role="u_requester"))
