"""Part deliveries: only 5 of 8 racks arrive. What has been received, what is still owed, and what a receipt may say.

An order is received in batches. It is "delivered" once every item is in (or a person accepts that the rest will not
come). Until then the supplier is chased for just the outstanding items. Pure functions: no database or clock.
"""

import json


class BadReceipt(ValueError):
    """The quantities entered cannot be right (unknown item, negative, more than is owed, or nothing at all)."""


def parse_batches(raw) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _key(description: str) -> str:
    return " ".join(str(description).lower().split())


def received_totals(batches: list[dict]) -> dict[str, int]:
    """Quantity received so far for each item (keyed by the item's lower-case name)."""
    totals: dict[str, int] = {}
    for batch in batches:
        for name, qty in (batch.get("items") or {}).items():
            totals[_key(name)] = totals.get(_key(name), 0) + int(qty)
    return totals


def progress(po_items: list[dict], batches: list[dict]) -> list[dict]:
    """One line per ordered item: ordered, received, outstanding."""
    got = received_totals(batches)
    lines = []
    for item in po_items:
        received = min(got.get(_key(item["description"]), 0), item["quantity"])
        lines.append({"description": item["description"], "ordered": item["quantity"], "received": received,
                      "outstanding": item["quantity"] - received})
    return lines


def units(lines: list[dict]) -> tuple[int, int]:
    """(received, ordered) summed over every item."""
    return sum(l["received"] for l in lines), sum(l["ordered"] for l in lines)


def is_complete(lines: list[dict]) -> bool:
    return all(l["outstanding"] == 0 for l in lines)


def is_partial(lines: list[dict]) -> bool:
    received, ordered = units(lines)
    return 0 < received < ordered


def normalise_receipt(po_items: list[dict], batches: list[dict], incoming: dict[str, int] | None) -> dict[str, int]:
    """What this receipt adds, keyed by the order's own item names. `incoming` None means "everything still owed".
    Raises BadReceipt for anything that cannot be right."""
    lines = progress(po_items, batches)
    owed = {_key(l["description"]): l for l in lines}
    if incoming is None:
        added = {l["description"]: l["outstanding"] for l in lines if l["outstanding"] > 0}
    else:
        added = {}
        for name, qty in incoming.items():
            line = owed.get(_key(name))
            if line is None:
                raise BadReceipt(f"'{name}' is not on this order.")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
                raise BadReceipt(f"The quantity for {line['description']} must be a whole number, zero or more.")
            if qty > line["outstanding"]:
                raise BadReceipt(
                    f"{qty} of {line['description']} is more than is still owed ({line['outstanding']}). "
                    f"If the supplier sent extra, note it and receive only what was ordered.")
            if qty:
                added[line["description"]] = qty
    if not added:
        raise BadReceipt("Enter at least one item that arrived." if incoming is not None else "Everything on this order has already been received.")
    return added


def summary(lines: list[dict]) -> str:
    """"5 of 8 received" or "everything received"."""
    received, ordered = units(lines)
    return "everything received" if received >= ordered else f"{received} of {ordered} received"


def outstanding_text(lines: list[dict]) -> str:
    """"Steel rack × 3, Shelf bracket × 8": what is still owed."""
    return ", ".join(f"{l['description']} × {l['outstanding']}" for l in lines if l["outstanding"] > 0)
