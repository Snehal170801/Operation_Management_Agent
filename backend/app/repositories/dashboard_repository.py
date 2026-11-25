"""Aggregate numbers for the live dashboard. Each query is a small count/sum, so the dashboard can be
refreshed every few seconds without downloading whole tables."""

from datetime import datetime

from app.db.connection import get_connection

# Stages where an open case is waiting on a person (keep in sync with notification_feed).
ATTENTION_STAGES = ("sourcing_stalled", "po_send_failed", "po_failed", "delivery_late")
LOW_STOCK_AT = 5
# Fetched so a pending approval can name what was asked for (it is not itself a stuck stage).
FETCH_STAGES = ATTENTION_STAGES + ("awaiting_approval",)


def totals(today: datetime) -> dict:
    conn = get_connection()
    try:
        cur = conn.cursor()
        c = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END), 0) FROM dbo.Cases"
        ).fetchone()
        stock = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(CASE WHEN quantity_available <= 0 THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN quantity_available > 0 AND quantity_available <= ? THEN 1 ELSE 0 END), 0) "
            "FROM dbo.Stock", LOW_STOCK_AT,
        ).fetchone()
        orders = cur.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_amount), 0), "
            "COALESCE(SUM(CASE WHEN created_at >= ? THEN total_amount ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN delivery_status = 'pending' THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN delivery_status = 'pending' AND expected_delivery_date < CAST(? AS DATE) "
            "THEN 1 ELSE 0 END), 0) FROM dbo.PurchaseOrders", today, today,
        ).fetchone()
        return {
            "cases_total": c[0], "cases_open": c[1], "cases_closed": c[2],
            "stock_items": stock[0], "out_of_stock": stock[1], "low_stock": stock[2],
            "suppliers": cur.execute("SELECT COUNT(*) FROM dbo.Vendors").fetchone()[0],
            "purchase_orders": orders[0], "ordered_total": float(orders[1]), "ordered_today": float(orders[2]),
            "awaiting_delivery": orders[3], "overdue_deliveries": orders[4],
            "pending_approvals": cur.execute("SELECT COUNT(*) FROM dbo.Approvals WHERE status = 'pending'").fetchone()[0],
            "invoices_to_review": cur.execute("SELECT COUNT(*) FROM dbo.Invoices WHERE status = 'mismatch'").fetchone()[0],
        }
    finally:
        conn.close()


def by_stage() -> list[tuple[str, int]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT stage, COUNT(*) AS n FROM dbo.Cases WHERE status = 'open' GROUP BY stage ORDER BY n DESC, stage ASC")
        return [(r.stage, r.n) for r in cur.fetchall()]
    finally:
        conn.close()


def created_per_day(since: datetime) -> list[tuple]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT CAST(created_at AS DATE) AS d, COUNT(*) AS n FROM dbo.Cases WHERE created_at >= ? "
            "GROUP BY CAST(created_at AS DATE) ORDER BY d ASC", since,
        )
        return [(r.d, r.n) for r in cur.fetchall()]
    finally:
        conn.close()


def approval_split() -> tuple[int, int]:
    """(approved by policy automatically, approved/rejected by a person)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT COALESCE(SUM(CASE WHEN status = 'auto_approved' THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN status IN ('approved', 'rejected') THEN 1 ELSE 0 END), 0) FROM dbo.Approvals"
        ).fetchone()
        return row[0], row[1]
    finally:
        conn.close()


def average_close_minutes() -> float | None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        value = cur.execute(
            "SELECT AVG(CAST(DATEDIFF(minute, created_at, updated_at) AS FLOAT)) FROM dbo.Cases WHERE status = 'closed'"
        ).fetchone()[0]
        return float(value) if value is not None else None
    finally:
        conn.close()


def recent_activity(limit: int = 10):
    """Newest things that happened, leaving out bookkeeping: 'stage.*' repeats another event, and the
    'step.*' signals belong to the Agent Flow page."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP (?) e.event_id, e.case_id, c.case_number, e.event_type, e.agent_name, e.created_at "
            "FROM dbo.CaseEvents e JOIN dbo.Cases c ON c.case_id = e.case_id "
            "WHERE e.event_type NOT LIKE 'stage.%' AND e.event_type NOT LIKE 'step.%' ORDER BY e.event_id DESC", limit,
        )
        return cur.fetchall()
    finally:
        conn.close()


def recent_agent_events(limit: int = 80):
    """Newest agent steps and hand-offs across every case (for the live board's feed). Progress ticks and the
    bookkeeping 'stage.*' events are left out."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP (?) e.event_id, e.case_id, c.case_number, e.event_type, e.agent_name, e.payload, e.created_at "
            "FROM dbo.CaseEvents e JOIN dbo.Cases c ON c.case_id = e.case_id "
            "WHERE e.event_type NOT LIKE 'stage.%' AND e.event_type <> 'step.progress' ORDER BY e.event_id DESC", limit,
        )
        return cur.fetchall()
    finally:
        conn.close()


def attention_cases():
    """Open cases stuck in a stage that needs a person, with a short summary of what was asked for."""
    placeholders = ", ".join("?" for _ in FETCH_STAGES)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT c.case_id, c.stage, c.status, c.updated_at, it.items AS items_summary "
            "FROM dbo.Cases c LEFT JOIN dbo.PurchaseRequests pr ON pr.case_id = c.case_id "
            "LEFT JOIN (SELECT purchase_request_id, STRING_AGG(CONCAT(description, ' (', quantity, ')'), ', ') AS items "
            "FROM dbo.PurchaseRequestItems GROUP BY purchase_request_id) it "
            f"ON it.purchase_request_id = pr.purchase_request_id WHERE c.status = 'open' AND c.stage IN ({placeholders})",
            *FETCH_STAGES,
        )
        return cur.fetchall()
    finally:
        conn.close()
