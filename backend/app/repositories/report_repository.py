"""Rows for the management report: everything belonging to the requests started in a period (or all time)."""

from app.db.connection import get_connection


def _run(sql: str, since) -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql + ("" if since is None else " WHERE c.created_at >= ?"), *([] if since is None else [since]))
        return cur.fetchall()
    finally:
        conn.close()


def cases_since(since):
    return _run("SELECT c.case_id, c.case_number, c.stage, c.status, c.created_at, c.updated_at FROM dbo.Cases c", since)


def rfqs_since(since):
    return _run(
        "SELECT r.case_id, r.vendor_id, v.name AS vendor_name, r.sent_at, r.replied_at, r.status "
        "FROM dbo.Rfqs r JOIN dbo.Cases c ON c.case_id = r.case_id JOIN dbo.Vendors v ON v.vendor_id = r.vendor_id", since)


def purchase_orders_since(since):
    return _run(
        "SELECT po.case_id, po.vendor_id, v.name AS vendor_name, po.total_amount, po.created_at, po.sent_at, po.status, "
        "po.expected_delivery_date, po.delivered_at, po.delivery_status, po.acknowledged_at "
        "FROM dbo.PurchaseOrders po JOIN dbo.Cases c ON c.case_id = po.case_id JOIN dbo.Vendors v ON v.vendor_id = po.vendor_id", since)


def invoices_since(since):
    return _run("SELECT i.case_id, i.vendor_id, i.status FROM dbo.Invoices i JOIN dbo.Cases c ON c.case_id = i.case_id", since)
