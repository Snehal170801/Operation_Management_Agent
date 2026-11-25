import logging

from app.agents import operations_agent, purchase_agent
from app.clients import azure_openai_client
from app.core import goods_issues, restock, stock_ledger
from app.core.exceptions import StockItemNotFound
from app.core.stock_matching import match_exact
from app.repositories import stock_repository

logger = logging.getLogger(__name__)

STOCK_MATCH_PROMPT = (
    "You are the Procurement Agent. You are given an item someone requested and the list of items we "
    "hold in stock. Decide whether the requested item is clearly the SAME product as exactly one stock "
    "item (e.g. 'screens' vs 'Monitor 24 inch' is NOT clear because the size is missing; 'tab' vs "
    "'Tablet' IS the same). If the request is vaguer than the stock item, more specific than it (a "
    "specific brand, size or spec the stock item doesn't have), or could fit several stock items, it is "
    "NOT a match. Respond ONLY with a JSON object with exactly one key: stock_item (the stock item's "
    "name copied exactly from the list, or null)."
)


def get_all_stock() -> list[dict]:
    rows = stock_repository.find_all_stock()
    return [
        {
            "item_description": row.item_description,
            "quantity_available": row.quantity_available,
            "updated_at": row.updated_at,
            "min_level": getattr(row, "min_level", None),
            "target_level": getattr(row, "target_level", None),
            "unit": getattr(row, "unit", None),
            "category": getattr(row, "category", None),
            "preferred_vendor_id": str(row.preferred_vendor_id) if getattr(row, "preferred_vendor_id", None) else None,
        }
        for row in rows
    ]


def receive_into_stock(received: dict[str, int], case_id: str | None = None, actor: str = "Procurement Agent") -> dict:
    """Goods bought to top up the shelf have arrived: add them to the matching stock rows, and record each in the stock history
    (who received them, and the reorder case). Returns {"added": [{item, added, now}], "unmatched": {line: quantity}};
    a line that matches no row is left alone."""
    names = [row.item_description for row in stock_repository.find_all_stock()]
    add, unmatched = restock.shelf_receipt(received, names)
    added = []
    for name, quantity in add.items():
        now = stock_repository.add_quantity(name, quantity, actor=actor, reason="restock_received", case_id=case_id)
        if now is None:
            unmatched[name] = unmatched.get(name, 0) + quantity
        else:
            added.append({"item": name, "added": quantity, "now": now})
    return {"added": added, "unmatched": unmatched}


def return_to_stock(case_id: str, taken: dict[str, int], actor: str) -> dict:
    """A request that was filled from stock has been cancelled: put what it took back on the shelf count, each recorded in the stock history
    against the case. Returns {"returned": [{item, returned, now}], "unmatched": {item: quantity}} (an item that no longer exists is reported)."""
    returned, unmatched = [], {}
    for name, quantity in taken.items():
        now = stock_repository.add_quantity(name, quantity, actor=actor, reason="cancelled_returned", case_id=case_id)
        if now is None:
            unmatched[name] = quantity
        else:
            returned.append({"item": name, "returned": quantity, "now": now})
    return {"returned": returned, "unmatched": unmatched}


def set_levels(item_description: str, min_level: int | None, target_level: int | None) -> bool:
    return stock_repository.set_levels(item_description, min_level, target_level)


def take_off_faulty(case_id: str, affected: list[dict], kind: str, actor: str) -> dict:
    """Goods from a reorder were reported wrong or damaged: take them back off the shelf count they were added to, and record it in
    the stock history. `affected` is [{"description", "quantity"}]. Only lines that match a stock row by the same words are touched
    (a doubtful match is left for a person), and a count never goes below zero.
    Returns {"removed": [{item, removed, now}], "unmatched": {line: quantity}}."""
    names = [row.item_description for row in stock_repository.find_all_stock()]
    take, unmatched = restock.shelf_receipt({a["description"]: a["quantity"] for a in affected}, names)
    removed = []
    for name, quantity in take.items():
        result = stock_repository.adjust_quantity(
            name, -quantity, actor=actor, reason="goods_issue", case_id=case_id, note=f"Reported: {goods_issues.KINDS.get(kind, kind)}.")
        if result is None:
            unmatched[name] = unmatched.get(name, 0) + quantity
        else:
            removed.append({"item": name, "removed": result[0] - result[1], "now": result[1]})
    return {"removed": removed, "unmatched": unmatched}


def put_back_faulty(case_id: str, removed: list[dict], resolution: str, actor: str) -> dict:
    """A goods problem on a reorder ended with the goods kept ("accepted") or replaced: what was taken off the count comes back.
    `removed` is what was actually taken off, [{"item", "removed"}], so a count that had been held at zero is not inflated.
    A supplier credit (the goods stay off) never calls this. Returns {"restored": [{item, added, now}], "unmatched": {item: n}}."""
    restored, unmatched = [], {}
    for line in removed:
        quantity = int(line.get("removed") or 0)
        if quantity <= 0:
            continue
        now = stock_repository.add_quantity(
            line["item"], quantity, actor=actor, reason=f"goods_issue_{resolution}", case_id=case_id,
            note="The supplier replaced the faulty goods." if resolution == "replaced" else "We are keeping the goods as they are.")
        if now is None:
            unmatched[line["item"]] = unmatched.get(line["item"], 0) + quantity
        else:
            restored.append({"item": line["item"], "added": quantity, "now": now})
    return {"restored": restored, "unmatched": unmatched}

def update_item(item_description: str, new_name: str, unit: str | None, category: str | None, preferred_vendor_id: str | None) -> bool:
    return stock_repository.update_item(item_description, new_name=new_name, unit=unit, category=category, preferred_vendor_id=preferred_vendor_id)


def remove_item(item_description: str, actor: str) -> int | None:
    """Remove the item (its history stays). Returns the count it had, or None when there was no such item."""
    return stock_repository.delete_item(item_description, actor)


def preferred_vendor_ids(items: list[dict]) -> list[str]:
    """The suppliers marked as preferred for any item on a request (a request line is matched to a stock item by the same words
    as everywhere else). Each supplier once, in the order of the request lines."""
    rows = {row.item_description: row for row in stock_repository.find_all_stock()}
    found: list[str] = []
    for item in items:
        name = match_exact(item.get("description") or "", list(rows))
        vendor = getattr(rows.get(name), "preferred_vendor_id", None) if name else None
        if vendor and str(vendor) not in found:
            found.append(str(vendor))
    return found


def get_history(item_description: str, limit: int = 200) -> list[dict]:
    """Every change to one item's count, newest first. An item that never existed (and has no history) is a 404."""
    rows = stock_repository.find_ledger(item_description, limit)
    if not rows and stock_repository.find_stock_by_description(item_description) is None:
        raise StockItemNotFound(item_description)
    return [stock_ledger.present({
        "entry_id": str(r.entry_id), "item_description": r.item_description, "old_quantity": r.old_quantity, "new_quantity": r.new_quantity,
        "change": r.new_quantity - r.old_quantity, "reason": r.reason, "actor": r.actor,
        "case_id": str(r.case_id) if r.case_id else None, "note": r.note, "created_at": r.created_at,
    }) for r in rows]


def upsert_stock(item_description: str, quantity_available: int, actor: str = "system") -> None:
    stock_repository.upsert_stock(item_description, stock_ledger.check_quantity(quantity_available), actor=actor)


def check_stock(case_id: str) -> dict:
    purchase_request = purchase_agent.get_purchase_request(case_id)
    stock_by_name = {row.item_description: row for row in stock_repository.find_all_stock()}

    checks = []
    for item in purchase_request["items"]:
        stock_name = _find_stock_item(item["description"], list(stock_by_name))
        stock_row = stock_by_name.get(stock_name) if stock_name else None
        available = stock_row.quantity_available if stock_row else 0
        requested = item["quantity"]
        # (reported to the live Agent Flow page; does nothing when no step is being tracked)
        operations_agent.report_progress(len(checks) + 1, len(purchase_request["items"]), item["description"])
        checks.append({
            "description": item["description"],
            # The stock row this line was matched to (may be worded differently from the request).
            "stock_item": stock_name,
            "requested": requested,
            "available": available,
            "sufficient": available >= requested,
        })

    all_sufficient = all(c["sufficient"] for c in checks)

    if all_sufficient:
        for c in checks:
            stock_repository.deduct_stock(c["stock_item"], c["requested"], case_id=case_id)

    operations_agent.publish_event(
        case_id, "stock.checked", agent_name="Procurement Agent",
        payload={"checks": checks, "sufficient": all_sufficient},
    )

    if all_sufficient:
        operations_agent.close_case(
            case_id, stage="fulfilled_from_stock",
            reason="All requested items were available in stock.",
        )
    else:
        operations_agent.set_stage(case_id, "sourcing_needed")

    return {"case_id": case_id, "sufficient": all_sufficient, "checks": checks}


def _find_stock_item(description: str, stock_names: list[str]) -> str | None:
    """Which stock row (by name) is this request line? Same words first; the AI only if that fails,
    and then only for a clear, unambiguous match. A miss just means it goes out to suppliers."""
    matched = match_exact(description, stock_names)
    if matched or not stock_names:
        return matched
    try:
        answer = azure_openai_client.ask_json(
            STOCK_MATCH_PROMPT,
            f"Requested item: {description}\nStock items: {stock_names}",
        ).get("stock_item")
    except Exception:
        logger.exception("Stock matching AI call failed for %r; treating as not in stock", description)
        return None
    # Never trust the AI blindly: it must name a row that really exists.
    return answer if isinstance(answer, str) and answer in stock_names else None
