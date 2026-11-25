import json
from datetime import date

from app.db.connection import get_connection

_SELECT = (
    "SELECT po.purchase_order_id, po.po_number, po.case_id, po.vendor_id, v.name AS vendor_name, "
    "po.total_amount, po.lead_time_days, po.terms, po.expected_delivery_date, po.items_json, "
    "po.status, po.created_at, po.sent_at, po.tax_rate_pct, po.tax_amount, po.total_with_tax, "
    "po.delivery_status, po.delivered_at, po.received_by, po.delivery_note, "
    "po.chase_count, po.last_chased_at, po.escalated_at, po.received_json, po.short_closed_at, "
    "po.cancel_requested_at, po.cancel_requested_by, po.cancel_reason, po.cancel_chase_count, po.last_cancel_chase_at, "
    "po.cancel_escalated_at, po.cancel_refused_at, "
    "po.acknowledged_at, po.acknowledged_by, po.confirm_chase_count, po.last_confirm_chase_at, po.confirm_escalated_at, po.vendor_issue, "
    "v.email AS vendor_email "
    "FROM dbo.PurchaseOrders po JOIN dbo.Vendors v ON v.vendor_id = po.vendor_id "
)


def insert_purchase_order(purchase_order_id: str, case_id: str, vendor_id: str, total_amount,
                          lead_time_days, terms, expected_delivery_date: date | None,
                          items: list[dict], tax: dict | None = None) -> int:
    """Creates the order and returns its generated po_number. `tax` is the order's tax lines (core/tax.py), if tax is tracked."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.PurchaseOrders (purchase_order_id, case_id, vendor_id, total_amount, "
            "lead_time_days, terms, expected_delivery_date, items_json, tax_rate_pct, tax_amount, total_with_tax) "
            "OUTPUT INSERTED.po_number VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            purchase_order_id, case_id, vendor_id, total_amount, lead_time_days, terms,
            expected_delivery_date, json.dumps(items),
            tax["rate_pct"] if tax else None, tax["tax_amount"] if tax else None, tax["total_with_tax"] if tax else None,
        )
        po_number = cur.fetchone()[0]
        conn.commit()
        return po_number
    finally:
        conn.close()


def find_case_id_by_po_number_and_vendor_email(po_number: int, vendor_email: str) -> str | None:
    """The case of order PO-<po_number>, but only if `vendor_email` is that order's own supplier."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP 1 po.case_id FROM dbo.PurchaseOrders po JOIN dbo.Vendors v ON v.vendor_id = po.vendor_id "
            "WHERE po.po_number = ? AND LOWER(v.email) = LOWER(?)",
            po_number, vendor_email,
        )
        row = cur.fetchone()
        return str(row.case_id) if row else None
    finally:
        conn.close()


def find_all():
    """Every purchase order, newest first (for the CSV export)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "ORDER BY po.created_at DESC")
        return cur.fetchall()
    finally:
        conn.close()


def find_purchase_order_by_case_id(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "WHERE po.case_id = ?", case_id)
        return cur.fetchone()
    finally:
        conn.close()


def sum_auto_approved_since(since) -> float:
    """Total value of purchase orders raised since `since` for automatically approved cases."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(COALESCE(po.total_with_tax, po.total_amount)), 0) FROM dbo.PurchaseOrders po "
            "WHERE po.created_at >= ? AND EXISTS ("
            "    SELECT 1 FROM dbo.Approvals a WHERE a.case_id = po.case_id AND a.status = 'auto_approved')",
            since,
        )
        return float(cur.fetchone()[0])
    finally:
        conn.close()


def find_open_deliveries():
    """Sent POs on open cases that are awaiting delivery and have a due date."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT po.purchase_order_id, po.po_number, po.case_id, v.name AS vendor_name, "
            "v.email AS vendor_email, po.expected_delivery_date, po.chase_count, "
            "po.last_chased_at, po.escalated_at, po.items_json, po.received_json "
            "FROM dbo.PurchaseOrders po "
            "JOIN dbo.Vendors v ON v.vendor_id = po.vendor_id "
            "JOIN dbo.Cases c ON c.case_id = po.case_id "
            "WHERE po.status = 'sent' AND po.delivery_status = 'pending' AND po.cancel_requested_at IS NULL "
            "AND po.expected_delivery_date IS NOT NULL AND c.status = 'open'"
        )
        return cur.fetchall()
    finally:
        conn.close()


def mark_chased(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET chase_count = chase_count + 1, "
            "last_chased_at = SYSUTCDATETIME() WHERE purchase_order_id = ?",
            purchase_order_id,
        )
        conn.commit()
    finally:
        conn.close()


def mark_escalated(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET escalated_at = SYSUTCDATETIME() "
            "WHERE purchase_order_id = ?",
            purchase_order_id,
        )
        conn.commit()
    finally:
        conn.close()


def mark_delivered(purchase_order_id: str, received_by: str, note: str | None) -> bool:
    """Atomically record receipt. False if it was already marked delivered."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET delivery_status = 'delivered', "
            "delivered_at = SYSUTCDATETIME(), received_by = ?, delivery_note = ? "
            "WHERE purchase_order_id = ? AND delivery_status = 'pending'",
            received_by, note, purchase_order_id,
        )
        updated = cur.rowcount == 1
        conn.commit()
        return updated
    finally:
        conn.close()


def update_status(purchase_order_id: str, status: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET status = ?, "
            "sent_at = CASE WHEN ? = 'sent' THEN SYSUTCDATETIME() ELSE sent_at END "
            "WHERE purchase_order_id = ?",
            status, status, purchase_order_id,
        )
        conn.commit()
    finally:
        conn.close()


def find_unconfirmed():
    """Orders emailed to the supplier, on open cases, that need watching: not yet confirmed, or with a problem the supplier raised."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            _SELECT + "JOIN dbo.Cases c ON c.case_id = po.case_id "
            "WHERE po.status = 'sent' AND (po.acknowledged_at IS NULL OR po.vendor_issue IS NOT NULL) AND c.status = 'open' AND po.cancel_requested_at IS NULL "
            "AND po.delivery_status = 'pending'"
        )
        return cur.fetchall()
    finally:
        conn.close()


def mark_acknowledged(purchase_order_id: str, by: str | None) -> bool:
    """Record the supplier's confirmation (clears any problem they had raised). False if it was already confirmed."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET acknowledged_at = SYSUTCDATETIME(), acknowledged_by = ?, vendor_issue = NULL "
            "WHERE purchase_order_id = ? AND acknowledged_at IS NULL",
            by, purchase_order_id,
        )
        done = cur.rowcount == 1
        conn.commit()
        return done
    finally:
        conn.close()


def mark_confirm_chased(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET confirm_chase_count = confirm_chase_count + 1, "
            "last_confirm_chase_at = SYSUTCDATETIME() WHERE purchase_order_id = ?",
            purchase_order_id,
        )
        conn.commit()
    finally:
        conn.close()


def mark_confirm_escalated(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.PurchaseOrders SET confirm_escalated_at = SYSUTCDATETIME() WHERE purchase_order_id = ?", purchase_order_id)
        conn.commit()
    finally:
        conn.close()


def set_vendor_issue(purchase_order_id: str, issue: str | None) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.PurchaseOrders SET vendor_issue = ? WHERE purchase_order_id = ?", issue, purchase_order_id)
        conn.commit()
    finally:
        conn.close()


def append_receipt(purchase_order_id: str, old_json: str | None, new_json: str) -> bool:
    """Record a batch of goods received. Only succeeds if nobody else recorded one meanwhile (so two people
    receiving at once cannot lose a batch) and the order is not already finished."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET received_json = ? WHERE purchase_order_id = ? AND delivery_status = 'pending' "
            "AND ((received_json IS NULL AND ? IS NULL) OR received_json = ?)",
            new_json, purchase_order_id, old_json, old_json,
        )
        done = cur.rowcount == 1
        conn.commit()
        return done
    finally:
        conn.close()


def mark_short_closed(purchase_order_id: str, by: str, note: str | None) -> bool:
    """The supplier will not send the rest and a person accepted that: the order counts as delivered as it stands."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET delivery_status = 'delivered', delivered_at = SYSUTCDATETIME(), received_by = ?, "
            "delivery_note = ?, short_closed_at = SYSUTCDATETIME() WHERE purchase_order_id = ? AND delivery_status = 'pending'",
            by, note, purchase_order_id,
        )
        done = cur.rowcount == 1
        conn.commit()
        return done
    finally:
        conn.close()


def find_cancelling():
    """Emailed orders where we have asked the supplier to cancel and have not had their answer, on open cases."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            _SELECT + "JOIN dbo.Cases c ON c.case_id = po.case_id "
            "WHERE po.status = 'sent' AND po.cancel_requested_at IS NOT NULL AND c.status = 'open'"
        )
        return cur.fetchall()
    finally:
        conn.close()


def mark_cancel_requested(purchase_order_id: str, by: str, reason: str | None) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET cancel_requested_at = SYSUTCDATETIME(), cancel_requested_by = ?, cancel_reason = ?, "
            "cancel_chase_count = 0, last_cancel_chase_at = NULL, cancel_escalated_at = NULL, cancel_refused_at = NULL "
            "WHERE purchase_order_id = ? AND cancel_requested_at IS NULL AND delivery_status = 'pending'",
            by, reason, purchase_order_id,
        )
        done = cur.rowcount == 1
        conn.commit()
        return done
    finally:
        conn.close()


def clear_cancel_request(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET cancel_requested_at = NULL, cancel_requested_by = NULL, cancel_reason = NULL, "
            "cancel_chase_count = 0, last_cancel_chase_at = NULL, cancel_escalated_at = NULL, cancel_refused_at = NULL "
            "WHERE purchase_order_id = ?", purchase_order_id,
        )
        conn.commit()
    finally:
        conn.close()


def mark_cancel_chased(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.PurchaseOrders SET cancel_chase_count = cancel_chase_count + 1, last_cancel_chase_at = SYSUTCDATETIME() "
                    "WHERE purchase_order_id = ?", purchase_order_id)
        conn.commit()
    finally:
        conn.close()


def mark_cancel_escalated(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.PurchaseOrders SET cancel_escalated_at = SYSUTCDATETIME() WHERE purchase_order_id = ?", purchase_order_id)
        conn.commit()
    finally:
        conn.close()


def mark_cancel_refused(purchase_order_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.PurchaseOrders SET cancel_refused_at = SYSUTCDATETIME() WHERE purchase_order_id = ?", purchase_order_id)
        conn.commit()
    finally:
        conn.close()


def update_items_and_total(purchase_order_id: str, items: list[dict], total_amount) -> None:
    """After a change to an order already with the supplier was agreed: the new quantities (and total, if it changed)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PurchaseOrders SET items_json = ?, total_amount = COALESCE(?, total_amount) WHERE purchase_order_id = ?",
            json.dumps(items), total_amount, purchase_order_id,
        )
        conn.commit()
    finally:
        conn.close()
