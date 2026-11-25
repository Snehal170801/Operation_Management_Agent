from datetime import datetime

from app.db.connection import get_connection

_SELECT = (
    "SELECT r.rfq_id, r.case_id, r.vendor_id, v.name AS vendor_name, v.email AS vendor_email, "
    "r.status, r.sent_at, r.last_contacted_at, r.reminder_count, r.deadline_at, r.replied_at "
    "FROM dbo.Rfqs r JOIN dbo.Vendors v ON v.vendor_id = r.vendor_id "
)


def insert_rfq(rfq_id: str, case_id: str, vendor_id: str, deadline_at: datetime) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.Rfqs (rfq_id, case_id, vendor_id, deadline_at) VALUES (?, ?, ?, ?)",
            rfq_id, case_id, vendor_id, deadline_at,
        )
        conn.commit()
    finally:
        conn.close()


def reopen(rfq_id: str, deadline_at: datetime) -> None:
    """Ask this supplier again: a fresh clock, no reminders sent yet, not yet replied."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Rfqs SET status = 'sent', sent_at = SYSUTCDATETIME(), last_contacted_at = SYSUTCDATETIME(), "
            "reminder_count = 0, deadline_at = ?, replied_at = NULL WHERE rfq_id = ?",
            deadline_at, rfq_id,
        )
        conn.commit()
    finally:
        conn.close()


def delete_rfq(case_id: str, vendor_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.Rfqs WHERE case_id = ? AND vendor_id = ?", case_id, vendor_id)
        conn.commit()
    finally:
        conn.close()


def find_rfqs_by_case_id(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_SELECT + "WHERE r.case_id = ? ORDER BY r.sent_at ASC", case_id)
        return cur.fetchall()
    finally:
        conn.close()


def find_vendor_id_by_email(case_id: str, email: str) -> str | None:
    """The vendor invited on this case whose email matches the sender, or None."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.vendor_id FROM dbo.Rfqs r JOIN dbo.Vendors v ON v.vendor_id = r.vendor_id "
            "WHERE r.case_id = ? AND LOWER(v.email) = LOWER(?)",
            case_id, email,
        )
        row = cur.fetchone()
        return str(row.vendor_id) if row else None
    finally:
        conn.close()


def mark_replied(case_id: str, vendor_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Rfqs SET status = 'replied', replied_at = SYSUTCDATETIME() "
            "WHERE case_id = ? AND vendor_id = ? AND status <> 'replied'",
            case_id, vendor_id,
        )
        conn.commit()
    finally:
        conn.close()


def mark_reminded(rfq_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Rfqs SET reminder_count = reminder_count + 1, "
            "last_contacted_at = SYSUTCDATETIME() WHERE rfq_id = ?",
            rfq_id,
        )
        conn.commit()
    finally:
        conn.close()


def mark_withdrawn(case_id: str) -> None:
    """The request for quotation was taken back: nobody is waited on for it any more."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.Rfqs SET status = 'withdrawn' WHERE case_id = ? AND status <> 'withdrawn'", case_id)
        conn.commit()
    finally:
        conn.close()


def mark_bounced(case_id: str, vendor_id: str) -> None:
    """The request for quotation never reached this supplier: nobody waits on them for it."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.Rfqs SET status = 'bounced' WHERE case_id = ? AND vendor_id = ? AND status = 'sent'", case_id, vendor_id)
        conn.commit()
    finally:
        conn.close()


def find_open_case_ids_for_vendor(vendor_id: str) -> list[str]:
    """Open requests where this supplier is being waited on (a quote request) or holds an emailed order."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.case_id FROM dbo.Rfqs r JOIN dbo.Cases c ON c.case_id = r.case_id "
            "WHERE r.vendor_id = ? AND r.status = 'sent' AND c.status = 'open' "
            "UNION SELECT po.case_id FROM dbo.PurchaseOrders po JOIN dbo.Cases c ON c.case_id = po.case_id "
            "WHERE po.vendor_id = ? AND po.status = 'sent' AND c.status = 'open'",
            vendor_id, vendor_id,
        )
        return [str(row[0]) for row in cur.fetchall()]
    finally:
        conn.close()
