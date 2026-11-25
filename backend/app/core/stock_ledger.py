"""Stock history: what a ledger entry says and how a count may change.

Pure rules (no database, no clock): the repository writes the rows, the agent decides when.
A count never goes below zero. When a change would (goods reported faulty that were already used, say), the count stops at zero
and the entry says so, so the history stays honest instead of the screen showing a negative number."""

from app.core.exceptions import InvalidInput

MAX_QUANTITY = 1_000_000

# reason -> what the history shows
REASONS = {
    "created": "Item added",
    "manual": "Changed by hand",
    "fulfilled_from_stock": "Used to fill a request",
    "restock_received": "Reorder received",
    "goods_issue": "Faulty goods taken off",
    "goods_issue_accepted": "Faulty goods kept, put back on the count",
    "goods_issue_replaced": "Replacement goods, put back on the count",
    "removed": "Item removed",
    "cancelled_returned": "Request cancelled, put back on the count",
}
SYSTEM_ACTORS = ("Procurement Agent", "system")


def reason_label(reason: str) -> str:
    return REASONS.get(reason, reason.replace("_", " ").capitalize())


def check_quantity(quantity) -> int:
    """A count someone types in: a whole number from 0 up."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not (0 <= quantity <= MAX_QUANTITY):
        raise InvalidInput(f"The quantity must be a whole number between 0 and {MAX_QUANTITY:,}.")
    return quantity


def clamp_after(old: int, delta: int) -> tuple[int, str | None]:
    """The new count after adding `delta` (negative to take off), never below zero, and a note when it had to stop at zero."""
    wanted = old + delta
    if wanted >= 0:
        return wanted, None
    return 0, f"Only {old} were counted, so {-delta} could not all be taken off."


def entry_for(old: int | None, new: int, reason: str, actor: str, case_id: str | None = None, note: str | None = None) -> dict | None:
    """The ledger entry for a change, or None when nothing changed (the count was set to what it already was).
    An item that did not exist yet starts from 0 and is always recorded."""
    created = old is None
    before = 0 if created else old
    if not created and before == new:
        return None
    return {
        "old_quantity": before, "new_quantity": new, "change": new - before,
        "reason": "created" if created else reason, "actor": (actor or "system").strip()[:150] or "system",
        "case_id": case_id, "note": (note or "").strip()[:300] or None,
    }


def present(row: dict) -> dict:
    """One ledger row as the screen wants it."""
    return {**row, "reason_label": reason_label(row["reason"]), "by_a_person": row["actor"] not in SYSTEM_ACTORS}


def removal_entry(old: int, actor: str, note: str | None = None) -> dict:
    """The last entry an item has when it is removed: whatever was left counts down to zero. Always recorded, even from zero,
    so the history says when the item went."""
    return {"old_quantity": old, "new_quantity": 0, "change": -old, "reason": "removed", "actor": (actor or "system").strip()[:150] or "system",
            "case_id": None, "note": (note or "").strip()[:300] or None}
