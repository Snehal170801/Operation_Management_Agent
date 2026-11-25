"""Editing and removing stock items: name, unit, category, preferred supplier. An item with open orders cannot be renamed or removed;
its history always stays."""

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.controllers import stock_controller
from app.core import stock_items
from app.core.exceptions import InvalidInput, RuleViolation, StockItemNotFound
from app.main import app
from app.models.auth_schemas import CurrentUser
from app.models.stock_schemas import UpdateStockItemRequest, UpsertStockRequest
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_restock import ADMIN, STORES, ordered_reorder

# ---- the rules -------------------------------------------------------------------------------------------------------------------


def test_names_are_tidied_and_must_say_something():
    assert stock_items.clean_name("  Steel   rack ") == "Steel rack"
    for bad in ("", "   ", None, "x" * 256):
        with pytest.raises(InvalidInput):
            stock_items.clean_name(bad)


def test_units_and_categories_are_short_and_empty_means_not_set():
    assert stock_items.clean_unit(" pcs ") == "pcs" and stock_items.clean_unit("m²") == "m²" and stock_items.clean_unit("") is None and stock_items.clean_unit(None) is None
    assert stock_items.clean_category("  Safety   gear ") == "Safety gear" and stock_items.clean_category("  ") is None
    for bad in ("x" * 31, "kg; DROP TABLE", "<b>"):
        with pytest.raises(InvalidInput):
            stock_items.clean_unit(bad)
    with pytest.raises(InvalidInput):
        stock_items.clean_category("c" * 61)


def test_a_new_name_may_not_be_one_another_item_already_has_but_the_same_item_may_change_capitals():
    names = ["Steel rack", "Lamp"]
    assert stock_items.check_rename("steel RACK", "Steel rack", names) == "steel RACK"        # the item itself: only the capitals change
    assert stock_items.check_rename(" Desk  lamp ", "Lamp", names) == "Desk lamp"
    with pytest.raises(InvalidInput, match="already a stock item called 'Lamp'"):
        stock_items.check_rename("LAMP ", "Steel rack", names)


def test_open_orders_and_open_requests_are_named_as_the_reasons_an_item_cannot_go():
    reasons = stock_items.blockers("Lamp", {"lamp": {"case_number": "REQ-2026-0007"}}, [("REQ-2026-0007", "Lamp"), ("REQ-2026-0009", "lamp"), ("REQ-2026-0010", "Chair")])
    assert reasons == ["a reorder is on its way (REQ-2026-0007)", "request REQ-2026-0009 is still open and asks for it"]   # the reorder is not named twice
    assert stock_items.blockers("Lamp", {}, [("REQ-1", "Chair")]) == []
    assert "cannot be removed yet" in stock_items.refusal("Lamp", "removed", ["a reorder is on its way (REQ-1)"])


# ---- the flows --------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch) -> World:
    w = standard_world(monkeypatch)
    from app.repositories import audit_repository
    w.audit = []
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: w.audit.append(a))
    w.add_stock("Lamp", 12, unit="pcs", category="Lighting")
    w.add_stock("Chair", 4)
    return w


def listing():
    return {s.item_description: s for s in stock_controller.get_all_stock()}


def change(item, **fields):
    stock_controller.update_item(UpdateStockItemRequest(item_description=item, **fields), STORES)


def test_the_list_shows_unit_category_and_the_preferred_supplier_by_name(w):
    w.add_stock("Cable", 9, preferred_vendor_id=w.vendor_id("Acme"))
    items = listing()
    assert (items["Lamp"].unit, items["Lamp"].category, items["Lamp"].preferred_vendor_name) == ("pcs", "Lighting", None)
    assert items["Cable"].preferred_vendor_id == w.vendor_id("Acme") and items["Cable"].preferred_vendor_name == "Acme"


def test_unit_and_category_can_be_set_changed_and_cleared(w):
    change("Chair", new_description="Chair", unit=" nos ", category="Furniture")
    assert (listing()["Chair"].unit, listing()["Chair"].category) == ("nos", "Furniture")
    change("Chair", unit=None, category=None)                                   # an empty value clears it
    assert (listing()["Chair"].unit, listing()["Chair"].category) == (None, None)
    assert w.stock["chair"].quantity_available == 4                              # the count is never touched here


def test_a_bad_unit_is_refused_and_nothing_changes(w):
    with pytest.raises(InvalidInput):
        change("Lamp", unit="kg; DROP TABLE")
    assert listing()["Lamp"].unit == "pcs"


def test_renaming_keeps_the_count_and_the_history_follows_the_new_name(w):
    stock_controller.upsert_stock(UpsertStockRequest(item_description="Lamp", quantity_available=20), STORES)
    change("Lamp", new_description="Desk lamp", unit="pcs", category="Lighting")
    assert "Lamp" not in listing() and listing()["Desk lamp"].quantity_available == 20
    assert [e.new_quantity for e in stock_controller.get_history("Desk lamp")] == [20]            # the change made before the rename
    with pytest.raises(StockItemNotFound):
        stock_controller.get_history("Lamp")                                                       # nothing is left under the old name


def test_a_name_another_item_has_is_refused_in_any_capitals(w):
    with pytest.raises(InvalidInput, match="already a stock item"):
        change("Lamp", new_description="chair")
    assert "Lamp" in listing()


def test_an_empty_new_name_is_refused(w):
    with pytest.raises(InvalidInput):
        change("Lamp", new_description="   ")


def test_a_rename_is_refused_while_a_reorder_for_the_item_is_on_its_way(w):
    case_id = ordered_reorder(w)                                                  # a reorder for "CCTV camera" is open
    with pytest.raises(RuleViolation, match="cannot be renamed yet.*reorder is on its way"):
        change("CCTV camera", new_description="Camera")
    change("CCTV camera", unit="pcs")                                             # a unit change is fine: orders match on the name
    assert listing()["CCTV camera"].unit == "pcs" and w.cases[case_id].status == "open"


def test_a_rename_that_only_changes_capitals_or_spaces_is_still_a_rename_and_follows_the_same_rule(w):
    ordered_reorder(w)
    with pytest.raises(RuleViolation):
        change("CCTV camera", new_description="cctv  CAMERA x")


def test_removing_an_item_leaves_a_last_history_entry_and_the_history_stays_readable(w):
    stock_controller.remove_item("Lamp", STORES)
    assert "Lamp" not in listing() and "lamp" not in w.stock
    (e,) = stock_controller.get_history("Lamp")                                    # still there after removal
    assert (e.reason, e.old_quantity, e.new_quantity, e.change, e.actor, e.reason_label) == ("removed", 12, 0, -12, "stores", "Item removed")
    assert [a for a in w.audit if a[2] == "stock.remove"]


def test_removing_an_item_that_is_already_at_zero_is_still_recorded(w):
    w.add_stock("Empty box", 0)
    stock_controller.remove_item("Empty box", STORES)
    assert stock_controller.get_history("Empty box")[0].reason == "removed"


def test_removal_is_refused_while_a_reorder_is_on_its_way_and_the_open_request_keeps_blocking_until_it_closes(w):
    case_id = ordered_reorder(w)
    with pytest.raises(RuleViolation, match=r"cannot be removed yet.*reorder is on its way \(REQ-"):
        stock_controller.remove_item("CCTV camera", STORES)
    assert "cctv camera" in w.stock
    case_pipeline.confirm_delivery(case_id, "recv", None)                          # everything arrived: no longer "on its way"
    with pytest.raises(RuleViolation, match="is still open and asks for it"):      # but the case stays open for the invoice
        stock_controller.remove_item("CCTV camera", STORES)


def test_removal_is_refused_while_an_open_request_asks_for_the_item(w):
    case_id = w.submit("50 cameras")                                                # not enough stock, so it goes out for quotes and stays open
    with pytest.raises(RuleViolation, match=w.cases[case_id].case_number):
        stock_controller.remove_item("CCTV camera", STORES)


def test_removal_is_allowed_when_the_only_request_for_it_is_closed(w):
    w.teach("5 cameras", [{"description": "CCTV camera", "quantity": 5}])
    w.submit("5 cameras")                                                           # filled from stock: the case is closed straight away
    stock_controller.remove_item("CCTV camera", STORES)
    assert "cctv camera" not in w.stock


def test_an_unknown_item_is_a_404_error_for_change_and_removal(w):
    with pytest.raises(StockItemNotFound):
        change("Unicorn saddle", unit="pcs")
    with pytest.raises(StockItemNotFound):
        stock_controller.remove_item("Unicorn saddle", STORES)


def test_a_preferred_supplier_can_be_chosen_changed_and_cleared(w):
    change("Lamp", unit="pcs", category="Lighting", preferred_vendor_id=w.vendor_id("Acme"))
    assert listing()["Lamp"].preferred_vendor_name == "Acme"
    change("Lamp", unit="pcs", category="Lighting", preferred_vendor_id=w.vendor_id("Globex").upper())      # ids are compared without regard to capitals
    assert listing()["Lamp"].preferred_vendor_name == "Globex"
    change("Lamp", unit="pcs", category="Lighting", preferred_vendor_id="")
    assert listing()["Lamp"].preferred_vendor_id is None


def test_a_preferred_supplier_that_does_not_exist_is_refused(w):
    with pytest.raises(InvalidInput, match="supplier does not exist"):
        change("Lamp", preferred_vendor_id="00000000-0000-0000-0000-000000000000")
    assert listing()["Lamp"].preferred_vendor_id is None


def test_every_edit_is_in_the_audit_log_with_before_and_after(w):
    change("Lamp", new_description="Desk lamp", unit="box", category="Lighting")
    entry = [a for a in w.audit if a[2] == "stock.update"][0]
    assert entry[1] == "stores" and "Desk lamp" in str(entry[-2]) and "pcs" in str(entry[-2])


# ---- the routes ------------------------------------------------------------------------------------------------------------------------

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def signed_in(monkeypatch, w):
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: role in ("admin", "u_stores") or permission == "stock:read")
    app.dependency_overrides[deps.get_current_user] = lambda: ADMIN
    yield
    app.dependency_overrides.clear()


def test_the_edit_route_changes_an_item_and_says_why_when_it_refuses(signed_in, w):
    assert client.patch("/stock/item", json={"item_description": "Lamp", "unit": "box", "category": "Lighting"}).status_code == 204
    assert w.stock["lamp"].unit == "box"
    assert client.patch("/stock/item", json={"item_description": "Lamp", "new_description": "Chair"}).status_code == 422
    assert client.patch("/stock/item", json={"item_description": "Nope"}).status_code == 404
    ordered_reorder(w)
    blocked = client.patch("/stock/item", json={"item_description": "CCTV camera", "new_description": "Camera"})
    assert blocked.status_code == 409 and "reorder is on its way" in blocked.json()["detail"]


def test_the_remove_route_removes_refuses_and_reports_unknown_items(signed_in, w):
    assert client.delete("/stock/item", params={"item": "Chair"}).status_code == 204 and "chair" not in w.stock
    assert client.delete("/stock/item", params={"item": "Chair"}).status_code == 404
    assert client.delete("/stock/item").status_code == 422
    ordered_reorder(w)
    assert client.delete("/stock/item", params={"item": "CCTV camera"}).status_code == 409


def test_someone_who_may_only_read_stock_cannot_edit_or_remove(monkeypatch, w):
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: permission == "stock:read")
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="viewer", role="u_view")
    try:
        assert client.patch("/stock/item", json={"item_description": "Lamp", "unit": "box"}).status_code == 403
        assert client.delete("/stock/item", params={"item": "Lamp"}).status_code == 403
        assert "lamp" in w.stock and w.stock["lamp"].unit == "pcs"
    finally:
        app.dependency_overrides.clear()


def test_nobody_signed_out_can_edit_or_remove():
    app.dependency_overrides.clear()
    assert client.patch("/stock/item", json={"item_description": "Lamp"}).status_code == 401
    assert client.delete("/stock/item", params={"item": "Lamp"}).status_code == 401
