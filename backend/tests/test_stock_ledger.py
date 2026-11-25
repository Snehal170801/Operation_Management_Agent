"""Stock history: every change to a stock count is written to a ledger (who, when, old, new, why, which case), by every code path that
changes stock. Faulty goods from a reorder come back off the count, with their own entry."""

import pytest
from fastapi.testclient import TestClient

from app.agents import procurement_agent
from app.api import deps
from app.controllers import stock_controller
from app.core import stock_ledger
from app.core.exceptions import InvalidInput, StockItemNotFound
from app.main import app
from app.models.auth_schemas import CurrentUser
from app.models.stock_schemas import UpsertStockRequest
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source
from .test_restock import ADMIN, STORES, ordered_reorder

# ---- the rules -------------------------------------------------------------------------------------------------------------------


def test_a_change_is_described_with_old_new_and_the_difference():
    e = stock_ledger.entry_for(20, 32, "restock_received", "recv", "case-1", "  part 1 ")
    assert e == {"old_quantity": 20, "new_quantity": 32, "change": 12, "reason": "restock_received", "actor": "recv", "case_id": "case-1", "note": "part 1"}


def test_setting_a_count_to_what_it_already_is_is_not_a_change():
    assert stock_ledger.entry_for(20, 20, "manual", "stores") is None


def test_a_new_item_starts_from_zero_and_is_always_recorded_as_added():
    e = stock_ledger.entry_for(None, 0, "manual", "stores")
    assert e["old_quantity"] == 0 and e["new_quantity"] == 0 and e["reason"] == "created" and e["change"] == 0


def test_a_count_never_goes_below_zero_and_says_so():
    assert stock_ledger.clamp_after(10, 4) == (14, None)
    assert stock_ledger.clamp_after(10, -10) == (0, None)
    new, note = stock_ledger.clamp_after(3, -5)
    assert new == 0 and "Only 3" in note and "5" in note


@pytest.mark.parametrize("bad", [-1, 1.5, "7", None, True, stock_ledger.MAX_QUANTITY + 1])
def test_a_typed_count_must_be_a_whole_number_in_range(bad):
    with pytest.raises(InvalidInput):
        stock_ledger.check_quantity(bad)


def test_the_labels_people_read_cover_every_reason_and_unknown_ones_still_read_well():
    assert stock_ledger.reason_label("manual") == "Changed by hand"
    assert stock_ledger.reason_label("something_new") == "Something new"
    assert stock_ledger.present({"reason": "fulfilled_from_stock", "actor": "Procurement Agent"})["by_a_person"] is False
    assert stock_ledger.present({"reason": "manual", "actor": "stores"})["by_a_person"] is True


# ---- every path that changes stock writes the ledger -----------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch) -> World:
    w = standard_world(monkeypatch)
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    return w


def history(item):
    return stock_controller.get_history(item)


def test_adding_a_new_item_by_hand_is_recorded_against_the_signed_in_person(w):
    stock_controller.upsert_stock(UpsertStockRequest(item_description="Lamp", quantity_available=12), STORES)
    (e,) = history("lamp")                                              # looked up by any capitalisation
    assert (e.reason, e.actor, e.old_quantity, e.new_quantity, e.change, e.by_a_person) == ("created", "stores", 0, 12, 12, True)
    assert e.reason_label == "Item added" and e.case_id is None and e.created_at


def test_changing_a_count_by_hand_records_old_and_new_and_who(w):
    stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=15), STORES)    # was 20
    stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=40), ADMIN)
    newest, older = history("CCTV camera")                              # newest first
    assert (newest.old_quantity, newest.new_quantity, newest.actor, newest.reason) == (15, 40, "snehalc@daccess.co", "manual")
    assert (older.old_quantity, older.new_quantity, older.actor) == (20, 15, "stores")


def test_saving_the_same_count_again_adds_nothing_to_the_history(w):
    stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=20), STORES)      # it already was 20
    assert history("CCTV camera") == []


def test_a_request_filled_from_stock_records_the_use_and_the_case(w):
    w.teach("5 cameras", [{"description": "CCTV camera", "quantity": 5}])
    case_id = w.submit("5 cameras")                                    # 20 in stock, so it is filled from stock
    assert w.stock["cctv camera"].quantity_available == 15
    (e,) = history("CCTV camera")
    assert (e.reason, e.old_quantity, e.new_quantity, e.change, e.actor, e.case_id) == ("fulfilled_from_stock", 20, 15, -5, "Procurement Agent", case_id)
    assert e.by_a_person is False and e.case_number == w.cases[case_id].case_number


def test_a_request_that_cannot_be_filled_from_stock_changes_nothing_and_records_nothing(w):
    w.submit("50 cameras")
    assert w.stock["cctv camera"].quantity_available == 20 and history("CCTV camera") == []


def test_received_goods_from_a_reorder_are_recorded_part_by_part_with_who_received_them(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 12})
    case_pipeline.confirm_delivery(case_id, "recv2", None)
    second, first = history("CCTV camera")
    assert (first.reason, first.actor, first.old_quantity, first.new_quantity, first.case_id) == ("restock_received", "recv", 20, 32, case_id)
    assert (second.actor, second.old_quantity, second.new_quantity) == ("recv2", 32, 50)


def test_goods_bought_for_a_request_leave_no_history(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert history("CCTV camera") == []


def test_the_history_is_per_item_and_the_screen_asks_for_one_item_at_a_time(w):
    w.add_stock("Lamp", 5)
    stock_controller.upsert_stock(UpsertStockRequest(item_description="Lamp", quantity_available=9), STORES)
    stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=1), STORES)
    assert [e.item_description for e in history("Lamp")] == ["Lamp"] and [e.item_description for e in history("CCTV camera")] == ["CCTV camera"]


def test_asking_for_the_history_of_an_item_that_never_existed_is_a_404_error(w):
    with pytest.raises(StockItemNotFound):
        history("Unicorn saddle")


def test_a_stock_change_that_cannot_be_typed_is_refused_before_anything_is_written(w):
    with pytest.raises(InvalidInput):
        stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=-4), STORES)
    assert w.stock["cctv camera"].quantity_available == 20 and history("CCTV camera") == []


# ---- wrong or damaged goods on a reorder ------------------------------------------------------------------------------------------

def test_faulty_goods_from_a_reorder_come_back_off_the_count_with_their_own_entry(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})        # 20 + 30 = 50
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, "boxes crushed", "recv")
    assert w.stock["cctv camera"].quantity_available == 45
    newest = history("CCTV camera")[0]
    assert (newest.reason, newest.change, newest.old_quantity, newest.new_quantity, newest.actor, newest.case_id) == ("goods_issue", -5, 50, 45, "recv", case_id)
    assert "damaged" in newest.note and newest.reason_label == "Faulty goods taken off"
    shown = [e for e in w.events[case_id] if e.event_type == "stock.reduced"]
    assert shown and shown[0].payload["items"] == [{"item": "CCTV camera", "removed": 5, "now": 45}]


def test_reporting_with_no_item_list_takes_off_everything_that_arrived(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 12})
    case_pipeline.report_goods_issue(case_id, "wrong_item", None, None, "recv")
    assert w.stock["cctv camera"].quantity_available == 20                                # 32 - 12: back to what it was


def test_a_problem_with_goods_bought_for_a_request_never_touches_the_stock(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    case_pipeline.confirm_delivery(case_id, "recv", None)
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    assert w.stock["cctv camera"].quantity_available == 20 and history("CCTV camera") == []


def test_faulty_goods_never_take_the_count_below_zero_and_the_history_says_why(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=2), STORES)    # most of it was used meanwhile
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    assert w.stock["cctv camera"].quantity_available == 0
    newest = history("CCTV camera")[0]
    assert newest.new_quantity == 0 and "could not all be taken off" in newest.note
    assert [e for e in w.events[case_id] if e.event_type == "stock.reduced"][0].payload["items"][0]["removed"] == 2


def test_faulty_goods_that_match_no_stock_row_are_left_for_a_person(w, monkeypatch):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 12})
    monkeypatch.setattr(procurement_agent.stock_repository, "find_all_stock", lambda: [])        # the item was removed from stock meanwhile
    case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    assert [e for e in w.events[case_id] if e.event_type == "stock.reduce_unmatched"]


def test_a_failure_taking_goods_off_stock_never_loses_the_problem_report(w, monkeypatch):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 12})

    def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(procurement_agent.stock_repository, "adjust_quantity", boom)
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    assert issue["status"] == "open"                                                          # the report is recorded and the supplier asked
    assert [e for e in w.events[case_id] if e.event_type == "stock.reduce_failed"]
    assert w.stock["cctv camera"].quantity_available == 32


def test_the_new_case_events_have_labels_people_can_read():
    from app.core.agent_flow import _DOMAIN_FEED as EVENT_INFO
    for kind in ("stock.reduced", "stock.reduce_unmatched", "stock.reduce_failed"):
        assert kind in EVENT_INFO


# ---- the route -------------------------------------------------------------------------------------------------------------------------

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def signed_in(monkeypatch, w):
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: role in ("admin", "u_stores") or permission == "stock:read")
    app.dependency_overrides[deps.get_current_user] = lambda: ADMIN
    yield
    app.dependency_overrides.clear()


def test_the_history_route_returns_the_entries_newest_first(signed_in, w):
    stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=15), STORES)
    r = client.get("/stock/history", params={"item": "CCTV camera"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["reason"] == "manual" and body[0]["old_quantity"] == 20 and body[0]["new_quantity"] == 15 and body[0]["actor"] == "stores"


def test_the_history_route_takes_item_names_with_spaces_and_odd_characters(signed_in, w):
    w.add_stock('Cable 2" / Cat6 (grey)', 3)
    stock_controller.upsert_stock(UpsertStockRequest(item_description='Cable 2" / Cat6 (grey)', quantity_available=8), STORES)
    r = client.get("/stock/history", params={"item": 'Cable 2" / Cat6 (grey)'})
    assert r.status_code == 200 and r.json()[0]["new_quantity"] == 8


def test_the_history_route_says_404_for_an_unknown_item_and_422_for_a_missing_name(signed_in, w):
    assert client.get("/stock/history", params={"item": "Unicorn saddle"}).status_code == 404
    assert client.get("/stock/history").status_code == 422


def test_the_manual_update_route_records_who_did_it(signed_in, w):
    assert client.post("/stock", json={"item_description": "Lamp", "quantity_available": 6}).status_code == 204
    assert history("Lamp")[0].actor == "snehalc@daccess.co"
    assert client.post("/stock", json={"item_description": "Lamp", "quantity_available": -1}).status_code == 422


def test_nobody_signed_out_can_read_the_history():
    app.dependency_overrides.clear()
    assert client.get("/stock/history", params={"item": "Lamp"}).status_code == 401


# ---- a goods problem on a reorder ends: what was taken off comes back, or stays off ----------------------------------------------------

def reported(w, taken=5, on_hand_first=30):
    """A reorder whose goods arrived, with `taken` of them reported damaged. Returns (case_id, issue)."""
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": on_hand_first})        # 20 + 30 = 50
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": taken}, None, "recv")
    assert w.stock["cctv camera"].quantity_available == 50 - taken
    return case_id, issue


@pytest.mark.parametrize("resolution", ["accepted", "replaced"])
def test_keeping_or_replacing_the_goods_puts_them_back_on_the_count_with_an_entry(w, resolution):
    case_id, issue = reported(w)
    case_pipeline.resolve_goods_issue(issue["issue_id"], resolution, None, "ok", "accounts")
    assert w.stock["cctv camera"].quantity_available == 50
    newest = history("CCTV camera")[0]
    assert (newest.reason, newest.change, newest.old_quantity, newest.new_quantity, newest.actor, newest.case_id) == (f"goods_issue_{resolution}", 5, 45, 50, "accounts", case_id)
    back = [e for e in w.events[case_id] if e.event_type == "stock.restored"]
    assert back[0].payload["items"] == [{"item": "CCTV camera", "added": 5, "now": 50}] and back[0].payload["resolution"] == resolution


def test_a_supplier_credit_leaves_the_goods_off_the_count(w):
    case_id, issue = reported(w)
    case_pipeline.resolve_goods_issue(issue["issue_id"], "credit", 4200.0, "10% credit note", "accounts")
    assert w.stock["cctv camera"].quantity_available == 45
    assert not [e for e in w.events[case_id] if e.event_type == "stock.restored"] and history("CCTV camera")[0].reason == "goods_issue"


def test_only_what_was_really_taken_off_comes_back_not_what_was_reported(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    stock_controller.upsert_stock(UpsertStockRequest(item_description="CCTV camera", quantity_available=2), STORES)       # most was used meanwhile
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")                      # only 2 could come off
    assert w.stock["cctv camera"].quantity_available == 0
    case_pipeline.resolve_goods_issue(issue["issue_id"], "accepted", None, None, "accounts")
    assert w.stock["cctv camera"].quantity_available == 2                                       # 2 back, not 5


def test_two_problems_on_one_case_each_restore_only_their_own_goods(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    first = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    second = case_pipeline.report_goods_issue(case_id, "wrong_item", {"CCTV camera": 3}, None, "recv")
    assert w.stock["cctv camera"].quantity_available == 42
    case_pipeline.resolve_goods_issue(second["issue_id"], "replaced", None, None, "accounts")
    assert w.stock["cctv camera"].quantity_available == 45                                      # only the second one's 3
    case_pipeline.resolve_goods_issue(first["issue_id"], "credit", 100.0, None, "accounts")
    assert w.stock["cctv camera"].quantity_available == 45


def test_a_problem_on_goods_bought_for_a_request_never_changes_stock_when_it_ends(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    case_pipeline.confirm_delivery(case_id, "recv", None)
    issue = case_pipeline.report_goods_issue(case_id, "damaged", {"CCTV camera": 5}, None, "recv")
    case_pipeline.resolve_goods_issue(issue["issue_id"], "accepted", None, None, "accounts")
    assert w.stock["cctv camera"].quantity_available == 20 and history("CCTV camera") == []


def test_putting_back_never_happens_twice_for_the_same_problem(w):
    case_id, issue = reported(w)
    case_pipeline.resolve_goods_issue(issue["issue_id"], "accepted", None, None, "accounts")
    case_pipeline._put_back_stock(case_id, issue, "accepted", "accounts")                          # called again by mistake
    assert w.stock["cctv camera"].quantity_available == 50 and len([e for e in w.events[case_id] if e.event_type == "stock.restored"]) == 1


def test_a_failure_putting_goods_back_never_loses_the_resolution(w, monkeypatch):
    case_id, issue = reported(w)

    def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(procurement_agent.stock_repository, "add_quantity", boom)
    resolved = case_pipeline.resolve_goods_issue(issue["issue_id"], "accepted", None, None, "accounts")
    assert resolved["status"] == "resolved" and resolved["resolution"] == "accepted"            # the resolution stands
    assert [e for e in w.events[case_id] if e.event_type == "stock.restore_failed"]
    assert w.stock["cctv camera"].quantity_available == 45


def test_goods_whose_stock_item_was_removed_meanwhile_are_reported_not_lost(w):
    case_id, issue = reported(w)
    del w.stock["cctv camera"]                                                                  # the item was removed from stock in the meantime
    case_pipeline.resolve_goods_issue(issue["issue_id"], "replaced", None, None, "accounts")
    assert [e for e in w.events[case_id] if e.event_type == "stock.restore_unmatched"]


def test_the_put_back_events_and_reasons_have_labels_people_can_read():
    from app.core.agent_flow import _DOMAIN_FEED as EVENT_INFO
    for kind in ("stock.restored", "stock.restore_unmatched", "stock.restore_failed"):
        assert kind in EVENT_INFO
    assert stock_ledger.reason_label("goods_issue_accepted") != "Goods issue accepted" and stock_ledger.reason_label("goods_issue_replaced")
