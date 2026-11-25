import json

from app.db.connection import get_connection

_SELECT = (
    "SELECT g.issue_id, g.case_id, g.purchase_order_id, g.kind, g.items_json, g.description, g.reported_by, g.reported_at, g.status, "
    "g.supplier_told_at, g.supplier_replied_at, g.chase_count, g.last_chased_at, g.escalated_at, g.resolution, g.credit_amount, "
    "g.resolution_note, g.resolved_by, g.resolved_at, g.return_status, g.return_ref, g.returned_at, g.returned_by, g.replacement_status, "
    "g.replacement_expected_at, g.replacement_received_at, g.credit_note_number, po.po_number, v.name AS vendor_name, v.email AS vendor_email "
    "FROM dbo.GoodsIssues g JOIN dbo.PurchaseOrders po ON po.purchase_order_id = g.purchase_order_id "
    "JOIN dbo.Vendors v ON v.vendor_id = po.vendor_id "
)


def insert_issue(issue_id: str, case_id: str, purchase_order_id: str, kind: str, items: list[dict], description: str | None, reported_by: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.GoodsIssues (issue_id, case_id, purchase_order_id, kind, items_json, description, reported_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            issue_id, case_id, purchase_order_id, kind, json.dumps(items), description, reported_by,
        )
        conn.commit()
    finally:
        conn.close()


def find_by_case(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "WHERE g.case_id = ? ORDER BY g.reported_at ASC", case_id)
        return cur.fetchall()
    finally:
        conn.close()


def find_by_id(issue_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "WHERE g.issue_id = ?", issue_id)
        return cur.fetchone()
    finally:
        conn.close()


def find_open():
    """Every open issue on an open case."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "JOIN dbo.Cases c ON c.case_id = g.case_id WHERE g.status = 'open' AND c.status = 'open' ORDER BY g.reported_at ASC")
        return cur.fetchall()
    finally:
        conn.close()


def mark_supplier_told(issue_id: str) -> None:
    _run("UPDATE dbo.GoodsIssues SET supplier_told_at = SYSUTCDATETIME() WHERE issue_id = ?", issue_id)


def mark_supplier_replied(case_id: str) -> None:
    """The supplier wrote back about the order: stop chasing them on every open issue of this case."""
    _run("UPDATE dbo.GoodsIssues SET supplier_replied_at = SYSUTCDATETIME() WHERE case_id = ? AND status = 'open' AND supplier_replied_at IS NULL", case_id)


def mark_chased(issue_id: str) -> None:
    _run("UPDATE dbo.GoodsIssues SET chase_count = chase_count + 1, last_chased_at = SYSUTCDATETIME() WHERE issue_id = ?", issue_id)


def mark_escalated(issue_id: str) -> None:
    _run("UPDATE dbo.GoodsIssues SET escalated_at = SYSUTCDATETIME() WHERE issue_id = ?", issue_id)


def mark_returned(issue_id: str, by: str, ref: str | None) -> bool:
    """The goods went back to the supplier. False if it was not open or was already marked."""
    return _changed("UPDATE dbo.GoodsIssues SET return_status = 'returned', return_ref = ?, returned_at = SYSUTCDATETIME(), returned_by = ? "
                    "WHERE issue_id = ? AND status = 'open' AND return_status IS NULL", ref, by, issue_id)


def mark_replacement_expected(issue_id: str) -> bool:
    """The supplier promised a replacement. They have answered, so the reminders stop. False if not open or already marked."""
    return _changed("UPDATE dbo.GoodsIssues SET replacement_status = 'expected', replacement_expected_at = SYSUTCDATETIME(), "
                    "supplier_replied_at = COALESCE(supplier_replied_at, SYSUTCDATETIME()) WHERE issue_id = ? AND status = 'open' AND replacement_status IS NULL", issue_id)


def mark_replacement_received(issue_id: str) -> bool:
    return _changed("UPDATE dbo.GoodsIssues SET replacement_status = 'received', replacement_received_at = SYSUTCDATETIME() "
                    "WHERE issue_id = ? AND status = 'open' AND replacement_status = 'expected'", issue_id)


def _changed(sql: str, *params) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, *params)
        done = cur.rowcount == 1
        conn.commit()
        return done
    finally:
        conn.close()


def resolve(issue_id: str, resolution: str, credit_amount, note: str | None, by: str, credit_note_number: str | None = None) -> bool:
    """Record how it ended. False if it was already resolved."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.GoodsIssues SET status = 'resolved', resolution = ?, credit_amount = ?, resolution_note = ?, resolved_by = ?, "
            "resolved_at = SYSUTCDATETIME(), credit_note_number = ? WHERE issue_id = ? AND status = 'open'",
            resolution, credit_amount, note, by, credit_note_number, issue_id,
        )
        done = cur.rowcount == 1
        conn.commit()
        return done
    finally:
        conn.close()


def _run(sql: str, *params) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, *params)
        conn.commit()
    finally:
        conn.close()
