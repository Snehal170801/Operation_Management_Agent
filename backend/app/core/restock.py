"""Low stock and re-ordering: when an item counts as low, how many to order, and whether an order is already on its way.
Pure rules; the screens and the pipeline do the rest."""

from datetime import datetime  # noqa: F401 (used in annotations)

from app.core.exceptions import InvalidInput

MAX_LEVEL = 1_000_000


def is_low(quantity: int, min_level: int | None) -> bool:
    """At or below the minimum. An item with no minimum is never low."""
    return min_level is not None and quantity <= min_level


def suggested_quantity(quantity: int, target_level: int | None) -> int | None:
    """How many to order to get back up to the target (at least one). None when no target has been set."""
    if target_level is None:
        return None
    return max(target_level - quantity, 1)


def check_levels(min_level: int | None, target_level: int | None) -> tuple[int | None, int | None]:
    """Both set, or both cleared; the target is never below the minimum."""
    if min_level is None and target_level is None:
        return None, None
    if min_level is None or target_level is None:
        raise InvalidInput("Set both the minimum and the target level, or clear both.")
    if not (0 <= min_level <= MAX_LEVEL and 0 <= target_level <= MAX_LEVEL):
        raise InvalidInput(f"Levels must be between 0 and {MAX_LEVEL:,}.")
    if target_level < min_level:
        raise InvalidInput("The target level cannot be lower than the minimum level.")
    return min_level, target_level


def check_quantity(quantity: int) -> int:
    if not (1 <= quantity <= MAX_LEVEL):
        raise InvalidInput(f"Order between 1 and {MAX_LEVEL:,} items.")
    return quantity


def shelf_receipt(received: dict[str, int], stock_names: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    """Split goods that arrived into (stock row -> quantity to add, lines that match no stock row). Same-product wording only
    (core/stock_matching): a wrong match would put the count on the wrong row, so a doubtful line is left for a person."""
    from app.core.stock_matching import match_exact
    add: dict[str, int] = {}
    unmatched: dict[str, int] = {}
    for description, quantity in received.items():
        if not isinstance(quantity, int) or quantity <= 0:
            continue
        row = match_exact(description, stock_names)
        if row:
            add[row] = add.get(row, 0) + quantity
        else:
            unmatched[description] = unmatched.get(description, 0) + quantity
    return add, unmatched


_ARRIVED_OR_ENDED = frozenset({"delivery.received", "delivery.short_closed", "case.closed", "case.cancelled", "case.merged_into"})


def on_the_way(events: list[dict]) -> bool:
    """A reorder is still on its way until all of it has arrived (or it was closed short, cancelled or finished). The invoice
    that follows does not matter here: by then the shelf has its goods."""
    return not any(e["event_type"] in _ARRIVED_OR_ENDED for e in events)


def auto_candidates(stock: list[dict], open_items: set[str], last_auto: dict[str, "datetime"], now: "datetime", cooldown_hours: float, limit: int) -> list[dict]:
    """The items an automatic reorder should be raised for right now. Each is at or below its minimum with both levels set, has no reorder
    already in progress (manual or automatic: `open_items`, lower-case names), and was not automatically reordered within the cool-down
    (`last_auto`: lower-case name -> when), so an item whose order was refused or cancelled is not re-raised every minute. The most
    short item first, at most `limit` per pass. [{item, quantity, on_hand, min_level}] where quantity brings it up to its target."""
    from datetime import timedelta
    found = []
    for s in stock:
        name = s["item_description"]
        low = is_low(s["quantity_available"], s.get("min_level"))
        want = suggested_quantity(s["quantity_available"], s.get("target_level")) if low else None
        if want is None or name.lower() in open_items:
            continue
        last = last_auto.get(name.lower())
        if last is not None and cooldown_hours > 0 and now - last < timedelta(hours=cooldown_hours):
            continue
        found.append({"item": name, "quantity": min(want, MAX_LEVEL), "on_hand": s["quantity_available"], "min_level": s["min_level"]})
    found.sort(key=lambda c: (c["on_hand"] - c["min_level"], c["item"].lower()))
    return found[:max(limit, 0)]


def open_orders(events: list[dict], is_open) -> dict[str, dict]:
    """item (lower case) -> {case_id, quantity} for re-orders whose case is still open. `events` are restock.requested events."""
    found: dict[str, dict] = {}
    for e in events:
        item = ((e.get("payload") or {}).get("item") or "").strip().lower()
        if item and is_open(e["case_id"]):
            found[item] = {"case_id": e["case_id"], "quantity": (e.get("payload") or {}).get("quantity")}
    return found
