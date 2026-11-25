import uuid
from datetime import date, datetime, timezone

from app.agents import operations_agent
from app.clients import azure_openai_client
from app.core import urgency
from app.core.config import settings
from app.core.exceptions import PurchaseRequestNotFound
from app.repositories import purchase_repository

SYSTEM_PROMPT = (
    "You are the Purchase Agent in a procurement system. Read the raw purchase "
    "request text and break it down into separate line items -- never merge "
    "different variants (e.g. different sizes, capacities, or specs of the same "
    "product) into one line. Respond ONLY with a JSON object with exactly these keys: "
    "items (array of objects, each with 'description' (string, includes the specific "
    "variant/spec) and 'quantity' (integer)), cost_center (string or null if not "
    "mentioned).\n\n"
    'Also give needed_by (the date the goods are needed by as YYYY-MM-DD, only if the text states a deadline such as "by Friday" or '
    '"within 3 days"; otherwise null) and urgent (true only if the text says urgent, asap, immediately or an emergency; otherwise false).\n\n'
    'Example: "need 5 jetsons: 1 with 16gb, 2 with 32gb, 2 with 64gb" should produce '
    'items: [{"description": "Jetson 16GB", "quantity": 1}, '
    '{"description": "Jetson 32GB", "quantity": 2}, '
    '{"description": "Jetson 64GB", "quantity": 2}] -- not a single merged line.'
)


def create_purchase_request(case_id: str, raw_request: str, needed_by: date | None = None, urgent: bool = False) -> dict:
    """`needed_by` and `urgent` are what the person entered in the form; they win over what the AI reads from the text."""
    today = datetime.now(timezone.utc).date()
    structured = azure_openai_client.ask_json(f"{SYSTEM_PROMPT}\n\nToday's date is {today:%A %d %B %Y} ({today.isoformat()}).", raw_request)
    needed, is_urgent = urgency.resolve(needed_by, urgent, structured.get("needed_by"), structured.get("urgent"), today, settings.URGENT_WITHIN_DAYS)

    purchase_request_id = str(uuid.uuid4())
    purchase_repository.insert_purchase_request(
        purchase_request_id=purchase_request_id,
        case_id=case_id,
        cost_center=structured.get("cost_center"),
        raw_request=raw_request,
        needed_by=needed, urgent=is_urgent,
    )
    purchase_repository.insert_purchase_request_items(
        purchase_request_id=purchase_request_id,
        items=structured["items"],
    )

    operations_agent.publish_event(
        case_id, "purchase_request.created", agent_name="Purchase Agent",
        payload={**structured, "needed_by": needed.isoformat() if needed else None, "urgent": is_urgent},
    )
    operations_agent.set_stage(case_id, "purchase_request_created")

    return get_purchase_request(case_id)


def create_restock_request(case_id: str, item: str, quantity: int, requested_by: str, needed_by: date | None = None, urgent: bool = False) -> dict:
    """A request to top up one stock item. The item and number are known, so nothing is read by the AI."""
    purchase_request_id = str(uuid.uuid4())
    raw = f"Restock {quantity} x {item} (stock is low). Raised by {requested_by}."
    purchase_repository.insert_purchase_request(
        purchase_request_id=purchase_request_id, case_id=case_id, cost_center=None, raw_request=raw, needed_by=needed_by, urgent=urgent,
    )
    purchase_repository.insert_purchase_request_items(purchase_request_id=purchase_request_id, items=[{"description": item, "quantity": quantity}])
    operations_agent.publish_event(
        case_id, "purchase_request.created", agent_name="Purchase Agent",
        payload={"items": [{"description": item, "quantity": quantity}], "cost_center": None, "restock": True,
                 "needed_by": needed_by.isoformat() if needed_by else None, "urgent": urgent},
    )
    operations_agent.set_stage(case_id, "purchase_request_created")
    return get_purchase_request(case_id)


def get_purchase_request(case_id: str) -> dict:
    row = purchase_repository.find_purchase_request_by_case_id(case_id)
    if row is None:
        raise PurchaseRequestNotFound(case_id)

    item_rows = purchase_repository.find_items_by_purchase_request_id(str(row.purchase_request_id))

    return {
        "purchase_request_id": str(row.purchase_request_id),
        "case_id": str(row.case_id),
        "cost_center": row.cost_center,
        "raw_request": row.raw_request,
        "items": [
            {"description": item.description, "quantity": item.quantity}
            for item in item_rows
        ],
        "created_at": row.created_at,
        "needed_by": getattr(row, "needed_by", None),
        "urgent": bool(getattr(row, "urgent", False)),
    }


def change_quantities(case_id: str, changes: list[dict], by: str, note: str | None) -> dict:
    """Apply already-validated quantity changes ([{"item", "from", "to"}]) to the request and record them."""
    request = get_purchase_request(case_id)
    for c in changes:
        purchase_repository.update_item_quantity(request["purchase_request_id"], c["item"], c["to"])
    operations_agent.publish_event(
        case_id, "request.changed", agent_name="Purchase Agent",
        payload={"changes": changes, "by": by, "note": note},
    )
    return get_purchase_request(case_id)


def apply_combined(case_id: str, merged: list[dict], needed_by, urgent: bool, by: str, other_number: str | None) -> dict:
    """Another request was folded into this one: the items become the combined list, and the more pressing date counts."""
    request = get_purchase_request(case_id)
    have = {i["description"]: i["quantity"] for i in request["items"]}
    changes, new_items = [], []
    for item in merged:
        if item["description"] in have:
            if have[item["description"]] != item["quantity"]:
                purchase_repository.update_item_quantity(request["purchase_request_id"], item["description"], item["quantity"])
                changes.append({"item": item["description"], "from": have[item["description"]], "to": item["quantity"]})
        else:
            new_items.append(item)
    if new_items:
        purchase_repository.insert_purchase_request_items(request["purchase_request_id"], new_items)
    if (needed_by, urgent) != (request.get("needed_by"), bool(request.get("urgent"))):
        purchase_repository.update_request_terms(request["purchase_request_id"], needed_by, urgent)
    operations_agent.publish_event(
        case_id, "request.changed", agent_name="Purchase Agent",
        payload={"changes": changes, "added": new_items, "by": by, "note": f"Combined with {other_number}" if other_number else "Combined with another request"},
    )
    return get_purchase_request(case_id)
