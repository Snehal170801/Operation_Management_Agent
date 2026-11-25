import json

from app.db.connection import get_connection

_SELECT = (
    "SELECT i.invoice_id, i.case_id, i.purchase_order_id, i.vendor_id, v.name AS vendor_name, "
    "po.po_number, i.invoice_number, i.total_amount, i.subtotal, i.tax_rate_pct, i.tax_amount, i.status, i.issues, i.source, "
    "i.decided_by, i.decision_note, i.created_at, i.decided_at "
    "FROM dbo.Invoices i "
    "JOIN dbo.Vendors v ON v.vendor_id = i.vendor_id "
    "JOIN dbo.PurchaseOrders po ON po.purchase_order_id = i.purchase_order_id "
)


def insert_invoice(invoice_id: str, case_id: str, purchase_order_id: str, vendor_id: str,
                   invoice_number, total_amount, raw_text: str, extracted: dict, status: str,
                   issues: list[str], source: str, tax: dict | None = None) -> None:
    tax = tax or {}
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.Invoices (invoice_id, case_id, purchase_order_id, vendor_id, invoice_number, "
            "total_amount, raw_text, extracted_json, status, issues, source, subtotal, tax_rate_pct, tax_amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            invoice_id, case_id, purchase_order_id, vendor_id, invoice_number, total_amount,
            raw_text, json.dumps(extracted), status, json.dumps(issues), source,
            tax.get("subtotal"), tax.get("tax_rate_pct"), tax.get("tax_amount"),
        )
        conn.commit()
    finally:
        conn.close()


def number_exists(vendor_id: str, invoice_number: str) -> bool:
    """True if this vendor already has a live (non-rejected) invoice with that number."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM dbo.Invoices WHERE vendor_id = ? AND invoice_number = ? AND status <> 'rejected'",
            vendor_id, invoice_number,
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def find_by_id(invoice_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "WHERE i.invoice_id = ?", invoice_id)
        return cur.fetchone()
    finally:
        conn.close()


def find_extractions_by_case_id(case_id: str):
    """The text of each invoice as it arrived and what the AI read from it."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT invoice_id, raw_text, extracted_json FROM dbo.Invoices WHERE case_id = ?", case_id)
        return cur.fetchall()
    finally:
        conn.close()


def find_by_case_id(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "WHERE i.case_id = ? ORDER BY i.created_at ASC", case_id)
        return cur.fetchall()
    finally:
        conn.close()


def find_all(status: str | None = None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        if status:
            cur.execute(_SELECT + "WHERE i.status = ? ORDER BY i.created_at DESC", status)
        else:
            cur.execute(_SELECT + "ORDER BY i.created_at DESC")
        return cur.fetchall()
    finally:
        conn.close()


def update_evaluation(invoice_id: str, status: str, issues: list[str]) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Invoices SET status = ?, issues = ? WHERE invoice_id = ?",
            status, json.dumps(issues), invoice_id,
        )
        conn.commit()
    finally:
        conn.close()


def decide_open(invoice_id: str, status: str, decided_by: str, note: str | None) -> bool:
    """A person resolves an invoice that was held or mismatched. False if it was not open."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Invoices SET status = ?, decided_by = ?, decision_note = ?, "
            "decided_at = SYSUTCDATETIME() WHERE invoice_id = ? AND status IN ('mismatch', 'on_hold')",
            status, decided_by, note, invoice_id,
        )
        updated = cur.rowcount == 1
        conn.commit()
        return updated
    finally:
        conn.close()
