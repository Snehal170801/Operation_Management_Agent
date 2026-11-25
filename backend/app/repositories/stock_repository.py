import uuid

import pyodbc

from app.core import stock_ledger
from app.core.exceptions import InvalidInput
from app.db.connection import get_connection

_COLUMNS = "stock_id, item_description, quantity_available, updated_at, min_level, target_level, unit, category, preferred_vendor_id"


def find_all_stock():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM dbo.Stock ORDER BY item_description ASC")
        return cur.fetchall()
    finally:
        conn.close()


def find_stock_by_description(description: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM dbo.Stock WHERE LOWER(item_description) = LOWER(?)", description)
        return cur.fetchone()
    finally:
        conn.close()


def _write_ledger(cur, stock_id, name: str, entry: dict | None) -> None:
    """The history row, in the SAME transaction as the count it describes: the number and its record can never disagree."""
    if entry is None:
        return
    cur.execute(
        "INSERT INTO dbo.StockLedger (stock_id, item_description, old_quantity, new_quantity, reason, actor, case_id, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        str(stock_id) if stock_id else None, name, entry["old_quantity"], entry["new_quantity"], entry["reason"], entry["actor"],
        entry["case_id"], entry["note"],
    )


def upsert_stock(description: str, quantity: int, *, actor: str = "system", reason: str = "manual", case_id: str | None = None,
                 note: str | None = None) -> None:
    """Set an item's count (add the item if it is new), and record the change."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT stock_id, item_description, quantity_available FROM dbo.Stock WHERE LOWER(item_description) = LOWER(?)",
            description,
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE dbo.Stock SET quantity_available = ?, updated_at = SYSUTCDATETIME() "
                "WHERE stock_id = ?",
                quantity, row.stock_id,
            )
            _write_ledger(cur, row.stock_id, row.item_description, stock_ledger.entry_for(row.quantity_available, quantity, reason, actor, case_id, note))
        else:
            stock_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO dbo.Stock (stock_id, item_description, quantity_available) "
                "VALUES (?, ?, ?)",
                stock_id, description, quantity,
            )
            _write_ledger(cur, stock_id, description, stock_ledger.entry_for(None, quantity, reason, actor, case_id, note))
        conn.commit()
    finally:
        conn.close()


def adjust_quantity(description: str, delta: int, *, actor: str, reason: str, case_id: str | None = None,
                    note: str | None = None) -> tuple[int, int] | None:
    """Add (or, with a negative `delta`, take off) in ONE statement, so two people acting at once cannot lose a number, and write
    the history row in the same transaction. The count stops at zero rather than going negative, and the history says when it had to.
    Returns (count before, count after), or None when there is no such item."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Stock SET quantity_available = CASE WHEN quantity_available + ? < 0 THEN 0 ELSE quantity_available + ? END, "
            "updated_at = SYSUTCDATETIME() "
            "OUTPUT deleted.stock_id, deleted.item_description, deleted.quantity_available, inserted.quantity_available "
            "WHERE LOWER(item_description) = LOWER(?)",
            delta, delta, description,
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None
        stock_id, name, before, after = row[0], row[1], int(row[2]), int(row[3])
        clamp_note = stock_ledger.clamp_after(before, delta)[1]
        _write_ledger(cur, stock_id, name, stock_ledger.entry_for(before, after, reason, actor, case_id, " ".join(filter(None, [note, clamp_note]))))
        conn.commit()
        return before, after
    finally:
        conn.close()


def deduct_stock(description: str, quantity: int, *, actor: str = "Procurement Agent", reason: str = "fulfilled_from_stock",
                 case_id: str | None = None, note: str | None = None) -> None:
    adjust_quantity(description, -quantity, actor=actor, reason=reason, case_id=case_id, note=note)


def add_quantity(description: str, quantity: int, *, actor: str = "Procurement Agent", reason: str = "restock_received",
                 case_id: str | None = None, note: str | None = None) -> int | None:
    """Add to an item's count. Returns the new count, or None when there is no such item."""
    result = adjust_quantity(description, quantity, actor=actor, reason=reason, case_id=case_id, note=note)
    return None if result is None else result[1]


def update_item(description: str, *, new_name: str, unit: str | None, category: str | None, preferred_vendor_id: str | None) -> bool:
    """Change an item's name, unit, category and preferred supplier (the counts and levels have their own functions). The item's
    history follows a new name. False when there is no such item; a name another item already has is refused."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT stock_id FROM dbo.Stock WHERE LOWER(item_description) = LOWER(?)", description)
        row = cur.fetchone()
        if row is None:
            return False
        try:
            cur.execute(
                "UPDATE dbo.Stock SET item_description = ?, unit = ?, category = ?, preferred_vendor_id = ?, updated_at = SYSUTCDATETIME() "
                "WHERE stock_id = ?",
                new_name, unit, category, preferred_vendor_id, row.stock_id,
            )
        except pyodbc.IntegrityError as exc:                              # someone else took the name a moment ago
            conn.rollback()
            raise InvalidInput("There is already a stock item with that name.") from exc
        cur.execute("UPDATE dbo.StockLedger SET item_description = ? WHERE stock_id = ?", new_name, row.stock_id)
        conn.commit()
        return True
    finally:
        conn.close()


def delete_item(description: str, actor: str) -> int | None:
    """Remove an item, leaving a last "removed" entry in its history (the history stays; it is a record). Returns the count it had,
    or None when there is no such item."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT stock_id, item_description, quantity_available FROM dbo.Stock WHERE LOWER(item_description) = LOWER(?)", description)
        row = cur.fetchone()
        if row is None:
            return None
        _write_ledger(cur, row.stock_id, row.item_description, stock_ledger.removal_entry(int(row.quantity_available), actor))
        cur.execute("DELETE FROM dbo.Stock WHERE stock_id = ?", row.stock_id)
        conn.commit()
        return int(row.quantity_available)
    finally:
        conn.close()


def find_ledger(description: str, limit: int = 200) -> list:
    """The history of one item, newest first."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP (?) entry_id, item_description, old_quantity, new_quantity, reason, actor, case_id, note, created_at "
            "FROM dbo.StockLedger WHERE LOWER(item_description) = LOWER(?) ORDER BY created_at DESC",
            limit, description,
        )
        return cur.fetchall()
    finally:
        conn.close()


def set_levels(description: str, min_level: int | None, target_level: int | None) -> bool:
    """Set (or clear) when an item counts as low and what to order up to. False when there is no such item."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Stock SET min_level = ?, target_level = ? WHERE LOWER(item_description) = LOWER(?)",
            min_level, target_level, description,
        )
        changed = cur.rowcount
        conn.commit()
        return changed > 0
    finally:
        conn.close()
