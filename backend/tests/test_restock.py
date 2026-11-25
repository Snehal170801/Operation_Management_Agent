"""Low stock: the admin sets when an item counts as low and what to order up to; Stores or the admin orders more in one click;
the order takes the same road as any request."""

import pytest

from app.agents import approval_agent, operations_agent
from app.controllers import stock_controller
from app.core import restock
from app.core.exceptions import InvalidInput, RuleViolation
from app.models.auth_schemas import CurrentUser
from app.models.stock_schemas import ReorderRequest, StockLevelsRequest

from .fake_world import World, standard_world


# ---- the rules ----

def test_low_means_at_or_below_the_minimum_and_no_minimum_is_never_low():
    assert restock.is_low(7, 10) and restock.is_low(10, 10) and not restock.is_low(11, 10)
    assert not restock.is_low(0, None)


def test_the_suggested_order_brings_stock_up_to_the_target():
    assert restock.suggested_quantity(7, 30) == 23
    assert restock.suggested_quantity(30, 30) == 1                 # at least one
    assert restock.suggested_quantity(7, None) is None


def test_levels_are_both_set_or_both_cleared_and_the_target_is_not_below_the_minimum():
    assert restock.check_levels(10, 30) == (10, 30) and restock.check_levels(5, 5) == (5, 5) and restock.check_levels(None, None) == (None, None)
    for bad in [(10, None), (None, 30), (30, 10), (-1, 5), (0, restock.MAX_LEVEL + 1)]:
        with pytest.raises(InvalidInput):
            restock.check_levels(*bad)


def test_an_order_for_nothing_or_far_too_much_is_refused():
    assert restock.check_quantity(1) == 1
    for bad in (0, -3, restock.MAX_LEVEL + 1):
        with pytest.raises(InvalidInput):
            restock.check_quantity(bad)


def test_only_orders_still_open_count_as_on_the_way():
    events = [{"case_id": "a", "payload": {"item": "Steel rack", "quantity": 5}}, {"case_id": "b", "payload": {"item": "Lamp", "quantity": 2}}]
    assert restock.open_orders(events, lambda c: c == "a") == {"steel rack": {"case_id": "a", "quantity": 5}}
    assert restock.open_orders([], lambda c: True) == {}


# ---- the flow ----

ADMIN = CurrentUser(user_id="1", username="snehalc@daccess.co", role="admin")
STORES = CurrentUser(user_id="2", username="stores", role="u_stores")


@pytest.fixture
def w(monkeypatch) -> World:
    w = standard_world(monkeypatch)
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    w.add_stock("Steel rack", 7, min_level=10, target_level=30)
    w.add_stock("Lamp", 50, min_level=10, target_level=40)
    w.add_stock("Chair", 3)                                         # no levels set
    return w


def listing():
    return {s.item_description: s for s in stock_controller.get_all_stock()}


def test_the_list_says_which_items_are_low_and_how_many_to_order(w):
    items = listing()
    assert items["Steel rack"].low and items["Steel rack"].suggested_quantity == 23
    assert not items["Lamp"].low and items["Lamp"].suggested_quantity is None
    assert not items["Chair"].low                                    # no minimum: never marked low


def test_ordering_starts_a_normal_request_that_asks_suppliers_for_prices(w):
    before = len(w.sent)
    result = stock_controller.reorder(ReorderRequest(item_description="steel rack", quantity=23), STORES)
    assert w.stage(result.case_id) == "awaiting_quotes"
    assert any("Request for quotation" in m[1] for m in w.sent[before:])
    req = w.requests[result.case_id]
    assert "Restock 23 x Steel rack" in req.raw_request and "stores" in req.raw_request
    assert [(i.description, i.quantity) for i in w.items[req.purchase_request_id]] == [("Steel rack", 23)]
    assert operations_agent.get_case_status(result.case_id)["requester_id"] == "stores"


def test_what_is_on_the_shelf_never_fills_a_reorder(w):
    # 25 on the shelf, asking for 5: an ordinary request would be filled from stock. A reorder must not be.
    w.add_stock("Bracket", 25, min_level=30, target_level=30)
    result = stock_controller.reorder(ReorderRequest(item_description="Bracket", quantity=5), ADMIN)
    assert w.stage(result.case_id) == "awaiting_quotes"
    assert w.stock["bracket"].quantity_available == 25


def test_the_list_then_shows_the_order_on_its_way_and_a_second_order_is_refused(w):
    result = stock_controller.reorder(ReorderRequest(item_description="Steel rack", quantity=23), STORES)
    order = listing()["Steel rack"].open_order
    assert order.case_id == result.case_id and order.quantity == 23 and order.case_number == result.case_number
    with pytest.raises(RuleViolation, match="already being ordered"):
        stock_controller.reorder(ReorderRequest(item_description="Steel rack", quantity=5), ADMIN)


def test_once_the_order_is_finished_the_item_can_be_ordered_again(w):
    result = stock_controller.reorder(ReorderRequest(item_description="Steel rack", quantity=23), STORES)
    operations_agent.close_case(result.case_id, stage="cancelled", reason="not needed")
    assert listing()["Steel rack"].open_order is None
    stock_controller.reorder(ReorderRequest(item_description="Steel rack", quantity=23), STORES)


def test_an_unknown_item_cannot_be_ordered(w):
    with pytest.raises(InvalidInput, match="no such stock item"):
        stock_controller.reorder(ReorderRequest(item_description="Piano", quantity=1), ADMIN)


def test_the_urgent_flag_and_date_carry_into_the_request(w):
    from datetime import date
    result = stock_controller.reorder(ReorderRequest(item_description="Steel rack", quantity=23, needed_by=date(2026, 10, 9), urgent=True), ADMIN)
    req = w.requests[result.case_id]
    assert req.urgent and req.needed_by == date(2026, 10, 9)


def test_setting_levels_checks_them_and_needs_an_existing_item(w):
    stock_controller.set_levels(StockLevelsRequest(item_description="Chair", min_level=5, target_level=12), ADMIN)
    assert listing()["Chair"].low and listing()["Chair"].suggested_quantity == 9
    stock_controller.set_levels(StockLevelsRequest(item_description="Chair"), ADMIN)           # cleared
    assert not listing()["Chair"].low
    with pytest.raises(InvalidInput):
        stock_controller.set_levels(StockLevelsRequest(item_description="Chair", min_level=9, target_level=3), ADMIN)
    with pytest.raises(InvalidInput, match="no such stock item"):
        stock_controller.set_levels(StockLevelsRequest(item_description="Piano", min_level=1, target_level=2), ADMIN)


def test_an_ordinary_request_is_unchanged_by_all_this(w):
    case_id = w.submit("10 laptops")
    assert w.stage(case_id) == "fulfilled_from_stock"                # laptops are in stock: still filled from the shelf


def test_with_automation_paused_a_reorder_waits_for_it(w, monkeypatch):
    from app.core import automation
    monkeypatch.setattr(automation, "is_paused", lambda: True)
    before = len(w.sent)
    result = stock_controller.reorder(ReorderRequest(item_description="Steel rack", quantity=23), ADMIN)
    assert w.stage(result.case_id) == "sourcing_needed"
    assert not any("Request for quotation" in m[1] for m in w.sent[before:])


# ---- goods that arrive for a reorder go into stock ----

from app.agents import procurement_agent  # noqa: E402
from app.orchestrator import case_pipeline  # noqa: E402

from .test_end_to_end import QUOTE_42K, QUOTE_45K, source  # noqa: E402


def events(w, case_id, kind):
    return [e for e in w.events[case_id] if e.event_type == kind]


def ordered_reorder(w, quantity=30):
    w.add_stock("CCTV camera", 20, min_level=25, target_level=50)       # replaces the standard 20 so the levels are set
    case_id = stock_controller.reorder(ReorderRequest(item_description="CCTV camera", quantity=quantity), STORES).case_id
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "awaiting_approval"                          # a reorder always waits for an approver
    pending = approval_agent.get_approvals("pending", case_id)[0]
    case_pipeline.decide_approval(pending["approval_id"], True, "approver", None)
    assert w.stage(case_id) == "po_issued"
    return case_id


def test_the_rule_splits_arrived_goods_into_shelf_rows_and_leftovers():
    add, unmatched = restock.shelf_receipt({"cctv camera": 5, "Steel rack": 2, "Lamp": 0, "Bad": -3}, ["CCTV camera", "Lamp"])
    assert add == {"CCTV camera": 5} and unmatched == {"Steel rack": 2}                       # zero and negative lines are ignored


def test_a_reorder_that_arrives_in_parts_tops_up_stock_part_by_part(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 12})
    assert w.stock["cctv camera"].quantity_available == 32
    assert events(w, case_id, "stock.increased")[0].payload["items"] == [{"item": "CCTV camera", "added": 12, "now": 32}]
    case_pipeline.confirm_delivery(case_id, "recv", None)                                      # the rest
    assert w.stock["cctv camera"].quantity_available == 50                                     # exactly the target
    assert not listing()["CCTV camera"].low


def test_goods_bought_for_a_request_never_touch_the_stock_count(w):
    case_id = w.submit("50 cameras")                                                           # an ordinary request: stock is 20, so it goes to suppliers
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert w.stock["cctv camera"].quantity_available == 20
    assert events(w, case_id, "stock.increased") == []


def test_closing_short_adds_nothing_more(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 12})
    case_pipeline.short_close_delivery(case_id, "recv", "supplier will not send more")
    assert w.stock["cctv camera"].quantity_available == 32


def test_a_line_that_matches_no_stock_row_is_reported_and_stock_is_left_alone(w):
    case_id = ordered_reorder(w)
    case_pipeline._top_up_stock(case_id, {"Mystery gadget": 4})
    assert events(w, case_id, "stock.topup_unmatched")[0].payload["items"] == {"Mystery gadget": 4}
    assert w.stock["cctv camera"].quantity_available == 20


def test_if_stock_cannot_be_updated_the_delivery_still_counts_and_the_case_says_so(w, monkeypatch):
    case_id = ordered_reorder(w)

    def boom(received):
        raise RuntimeError("database down")

    monkeypatch.setattr(procurement_agent, "receive_into_stock", boom)
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert w.stage(case_id) in ("delivered", "completed")                                      # the goods are recorded all the same
    assert events(w, case_id, "stock.topup_failed")
    assert w.stock["cctv camera"].quantity_available == 20


def test_the_case_events_have_labels_people_can_read():
    from app.core.agent_flow import _DOMAIN_FEED as EVENT_INFO
    for kind in ("restock.requested", "stock.increased", "stock.topup_unmatched", "stock.topup_failed"):
        assert kind in EVENT_INFO


def test_the_order_is_no_longer_on_its_way_once_all_of_it_has_arrived_even_if_the_invoice_is_pending(w):
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 12})
    assert listing()["CCTV camera"].open_order is not None                  # part has come, the rest is still awaited
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert w.cases[case_id].status == "open"                                # the case stays open for the invoice
    assert listing()["CCTV camera"].open_order is None


def test_what_counts_as_still_on_its_way():
    assert restock.on_the_way([{"event_type": "po.issued"}, {"event_type": "delivery.partial"}])
    for done in ("delivery.received", "delivery.short_closed", "case.closed", "case.cancelled", "case.merged_into"):
        assert not restock.on_the_way([{"event_type": "po.issued"}, {"event_type": done}])


def test_a_reorder_always_needs_an_approver_however_small_the_amount(w):
    case_id = stock_controller.reorder(ReorderRequest(item_description="CCTV camera", quantity=30), STORES).case_id
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})                 # well under the auto-approve limit, two reliable quotes
    assert w.stage(case_id) == "awaiting_approval"
    pending = approval_agent.get_approvals("pending", case_id)[0]
    assert "Every reorder needs an approver" in " ".join(pending["reasons"])
    assert not [m for m in w.sent if "Purchase order" in m[1]]                   # nothing was ordered


def test_an_ordinary_request_of_the_same_size_is_still_approved_automatically(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"


def test_refusing_a_reorder_orders_nothing_and_frees_the_item(w):
    case_id = stock_controller.reorder(ReorderRequest(item_description="CCTV camera", quantity=30), STORES).case_id
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    pending = approval_agent.get_approvals("pending", case_id)[0]
    case_pipeline.decide_approval(pending["approval_id"], False, "approver", "not now")
    assert w.cases[case_id].status == "closed"
    assert listing()["CCTV camera"].open_order is None


def test_the_rule_adds_the_reason_first_only_for_a_reorder():
    from app.core.approval_policy import RESTOCK_REASON, human_review_reasons
    quote = {"price": 100.0}
    assert human_review_reasons(quote, 5.0, 3, restock=True)[0] == RESTOCK_REASON
    assert human_review_reasons(quote, 5.0, 3) == []
