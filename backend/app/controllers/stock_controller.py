from app.agents import operations_agent, procurement_agent, purchase_agent, vendor_agent
from app.core import audit, restock, stock_items
from app.core.exceptions import StockItemNotFound
from app.core.exceptions import InvalidInput, RuleViolation
from app.models.auth_schemas import CurrentUser
from app.models.stock_schemas import (
    OpenOrder,
    ReorderRequest,
    ReorderResponse,
    StockHistoryEntry,
    StockItemResponse,
    StockLevelsRequest,
    UpdateStockItemRequest,
    UpsertStockRequest,
)
from app.orchestrator import case_pipeline


def _open_orders() -> dict[str, dict]:
    """Re-orders still in progress, by item. A case that cannot be read (deleted) does not count."""
    def is_open(case_id: str) -> bool:
        try:
            return operations_agent.get_case_status(case_id)["status"] == "open" and restock.on_the_way(operations_agent.get_case_events(case_id))
        except Exception:
            return False
    return restock.open_orders(operations_agent.get_events_of_types(("restock.requested",)), is_open)


def _case_number(case_id: str) -> str | None:
    try:
        return operations_agent.get_case_status(case_id)["case_number"]
    except Exception:
        return None


def get_all_stock() -> list[StockItemResponse]:
    stock = procurement_agent.get_all_stock()
    orders = _open_orders() if any(s.get("min_level") is not None for s in stock) else {}
    suppliers = {v["vendor_id"].lower(): v["name"] for v in vendor_agent.get_all_vendors()} if any(s.get("preferred_vendor_id") for s in stock) else {}
    out = []
    for s in stock:
        low = restock.is_low(s["quantity_available"], s.get("min_level"))
        order = orders.get(s["item_description"].lower())
        out.append(StockItemResponse(
            **s, low=low, suggested_quantity=restock.suggested_quantity(s["quantity_available"], s.get("target_level")) if low else None,
            open_order=OpenOrder(case_id=order["case_id"], case_number=_case_number(order["case_id"]), quantity=order["quantity"]) if order else None,
            preferred_vendor_name=suppliers.get((s.get("preferred_vendor_id") or "").lower()),
        ))
    return out


def _open_request_lines() -> list[tuple[str, str]]:
    """(case number, item line) for every request that is still open. A request that cannot be read does not count."""
    lines = []
    for case in operations_agent.get_all_cases(None):
        if case["status"] != "open":
            continue
        try:
            request = purchase_agent.get_purchase_request(case["case_id"])
        except Exception:
            continue
        number = case.get("case_number") or case["case_id"]
        lines.extend((number, item["description"]) for item in request.get("items", []))
    return lines


def _why_not(name: str, action: str) -> str | None:
    """The refusal to give when this item cannot be removed or renamed right now (open orders refer to it), or None."""
    orders = {k: {**v, "case_number": _case_number(v["case_id"])} for k, v in _open_orders().items()}
    reasons = stock_items.blockers(name, orders, _open_request_lines())
    return stock_items.refusal(name, action, reasons) if reasons else None


def _find(item_description: str) -> dict:
    wanted = item_description.strip().lower()
    found = next((s for s in procurement_agent.get_all_stock() if s["item_description"].lower() == wanted), None)
    if found is None:
        raise StockItemNotFound(item_description.strip())
    return found


def update_item(request: UpdateStockItemRequest, user: CurrentUser) -> None:
    """Rename an item or change its unit, category or preferred supplier. A rename is refused while open orders refer to the old name."""
    current = _find(request.item_description)
    name = current["item_description"]
    new_name = stock_items.check_rename(request.new_description, name, [s["item_description"] for s in procurement_agent.get_all_stock()])         if request.new_description is not None else name
    if new_name != name:
        refusal = _why_not(name, "renamed")
        if refusal:
            raise RuleViolation(refusal)
    unit, category = stock_items.clean_unit(request.unit), stock_items.clean_category(request.category)
    supplier = (request.preferred_vendor_id or "").strip() or None
    if supplier and not any(v["vendor_id"].lower() == supplier.lower() for v in vendor_agent.get_all_vendors()):
        raise InvalidInput("That supplier does not exist.")
    procurement_agent.update_item(name, new_name, unit, category, supplier)
    audit.record(
        "stock.update", actor_user_id=user.user_id, actor_username=user.username, target_type="stock", target_id=new_name,
        detail={"from": {"name": name, "unit": current.get("unit"), "category": current.get("category"), "preferred_vendor_id": current.get("preferred_vendor_id")},
                "to": {"name": new_name, "unit": unit, "category": category, "preferred_vendor_id": supplier}},
    )


def remove_item(item_description: str, user: CurrentUser) -> None:
    """Remove an item. Refused while an open order or request refers to it. The item's history stays."""
    current = _find(item_description)
    name = current["item_description"]
    refusal = _why_not(name, "removed")
    if refusal:
        raise RuleViolation(refusal)
    if procurement_agent.remove_item(name, user.username) is None:
        raise StockItemNotFound(name)
    audit.record(
        "stock.remove", actor_user_id=user.user_id, actor_username=user.username, target_type="stock", target_id=name,
        detail={"quantity_when_removed": current["quantity_available"]},
    )


def upsert_stock(request: UpsertStockRequest, user: CurrentUser) -> None:
    procurement_agent.upsert_stock(request.item_description, request.quantity_available, actor=user.username)
    audit.record(
        "stock.set", actor_user_id=user.user_id, actor_username=user.username, target_type="stock", target_id=request.item_description,
        detail={"quantity": request.quantity_available},
    )


def get_history(item_description: str) -> list[StockHistoryEntry]:
    """The history of one item, newest first, with each case number so the screen can link to it."""
    numbers: dict[str, str | None] = {}
    out = []
    for e in procurement_agent.get_history(item_description.strip()):
        if e["case_id"] and e["case_id"] not in numbers:
            numbers[e["case_id"]] = _case_number(e["case_id"])
        out.append(StockHistoryEntry(**e, case_number=numbers.get(e["case_id"]) if e["case_id"] else None))
    return out


def set_levels(request: StockLevelsRequest, user: CurrentUser) -> None:
    low, target = restock.check_levels(request.min_level, request.target_level)
    if not procurement_agent.set_levels(request.item_description, low, target):
        raise InvalidInput("There is no such stock item. Add it first.")
    audit.record(
        "stock.levels", actor_user_id=user.user_id, actor_username=user.username, target_type="stock", target_id=request.item_description,
        detail={"min_level": low, "target_level": target},
    )


def reorder(request: ReorderRequest, user: CurrentUser) -> ReorderResponse:
    quantity = restock.check_quantity(request.quantity)
    item = next((s for s in procurement_agent.get_all_stock() if s["item_description"].lower() == request.item_description.strip().lower()), None)
    if item is None:
        raise InvalidInput("There is no such stock item.")
    name = item["item_description"]
    waiting = _open_orders().get(name.lower())
    if waiting:
        raise RuleViolation(f"{name} is already being ordered ({_case_number(waiting['case_id']) or 'an open request'}).")
    case_id = case_pipeline.restock_item(name, quantity, user.username, needed_by=request.needed_by, urgent=request.urgent)
    audit.record(
        "stock.reorder", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
        detail={"item": name, "quantity": quantity},
    )
    return ReorderResponse(case_id=case_id, case_number=_case_number(case_id))
