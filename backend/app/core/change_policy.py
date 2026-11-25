"""Cancelling or changing a request: what is still possible, and what has to happen, depends on how far it has got.

  before_order  no order has gone to a supplier yet: cancel or change freely (suppliers who were asked are told)
  cancelling    the order was emailed and we have asked the supplier to cancel it: waiting for their answer
  after_order   the order is with the supplier: cancelling means asking them; a change is handled by the PO desk
  delivered     goods have arrived (all or part): too late, a different route (a new request, or a goods issue)
  closed        finished

Pure functions over the case, its purchase order and its events; no database or clock.
"""

CHANGE_REQUESTED = "po.change_requested"
CHANGE_HANDLED = "po.change_handled"

MAX_QUANTITY = 100_000


class BadChange(ValueError):
    """The quantities cannot be right (unknown item, not a whole number, out of range, or nothing changes)."""


def phase(case: dict, po: dict | None, delivery: dict | None) -> str:
    if case["status"] != "open":
        return "from_stock" if case.get("stage") == "fulfilled_from_stock" else "closed"
    if po is None or po.get("status") not in ("sent",):
        return "before_order"                 # no order, or one that was never emailed
    if po.get("cancel_requested_at"):
        return "cancelling"
    if delivery and (delivery.get("delivery_status") == "delivered" or delivery.get("batches")):
        return "delivered"
    return "after_order"


def options(case: dict, po: dict | None, delivery: dict | None, events: list[dict]) -> dict:
    """What the requester may do now and a plain sentence about it."""
    p = phase(case, po, delivery)
    pending = pending_change(events)
    can_cancel = p in ("before_order", "after_order", "from_stock")
    can_change = p == "before_order" or (p == "after_order" and pending is None)
    note = {
        "before_order": "No order has gone to a supplier yet, so you can cancel or change this request.",
        "after_order": "The order is already with the supplier. Cancelling asks them to cancel it; a change is passed to the purchasing team.",
        "cancelling": "We have asked the supplier to cancel the order and are waiting for their answer.",
        "delivered": "The goods have already arrived, so this can no longer be cancelled or changed here. Raise a new request if you need something else.",
        "from_stock": "This was filled from stock. If you no longer need it, cancel it and Stores will put it back (if it has not been handed over yet).",
        "closed": "This request is finished.",
    }[p]
    return {"phase": p, "can_cancel": can_cancel, "can_change": can_change, "pending_change": pending, "note": note}


def pending_change(events: list[dict]) -> dict | None:
    """A quantity change asked for after the order went out and not yet dealt with: {changes, by, note, at}, or None."""
    mine = [(e["created_at"], i, e) for i, e in enumerate(events) if e["event_type"] in (CHANGE_REQUESTED, CHANGE_HANDLED)]
    last = max(mine, key=lambda t: (t[0], t[1]))[2] if mine else None      # (list order breaks a tie in time)
    if last is None or last["event_type"] == CHANGE_HANDLED:
        return None
    payload = last.get("payload") or {}
    return {"changes": payload.get("changes", []), "by": payload.get("by"), "note": payload.get("note"), "at": last["created_at"]}


def plan_changes(items: list[dict], wanted: dict[str, int]) -> list[dict]:
    """The lines that really change, as [{"item", "from", "to"}] using the request's own item names.
    Raises BadChange for anything that cannot be right."""
    by_name = {" ".join(i["description"].lower().split()): i for i in items}
    changes = []
    for name, qty in wanted.items():
        item = by_name.get(" ".join(str(name).lower().split()))
        if item is None:
            raise BadChange(f"'{name}' is not on this request.")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1 or qty > MAX_QUANTITY:
            raise BadChange(f"The quantity for {item['description']} must be a whole number from 1 to {MAX_QUANTITY:,}. To remove it, cancel the request.")
        if qty != item["quantity"]:
            changes.append({"item": item["description"], "from": item["quantity"], "to": qty})
    if not changes:
        raise BadChange("Nothing was changed. Enter a different quantity for at least one item.")
    return changes


def changes_text(changes: list[dict]) -> str:
    return "; ".join(f"{c['item']}: {c['from']} → {c['to']}" for c in changes)
