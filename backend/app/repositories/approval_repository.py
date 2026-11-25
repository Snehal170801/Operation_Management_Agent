import json

from app.db.connection import get_connection

_COLUMNS = (
    "approval_id, case_id, approval_type, status, reasons, "
    "decided_by, decision_note, created_at, decided_at, reminder_count, last_reminded_at"
)


def insert_approval(approval_id: str, case_id: str, approval_type: str, status: str,
                    reasons: list[str], decided_by: str = None) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.Approvals "
            "(approval_id, case_id, approval_type, status, reasons, decided_by, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, CASE WHEN ? = 'pending' THEN NULL ELSE SYSUTCDATETIME() END)",
            approval_id, case_id, approval_type, status, json.dumps(reasons), decided_by, status,
        )
        conn.commit()
    finally:
        conn.close()


def supersede_pending(case_id: str, approval_type: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Approvals SET status = 'superseded', decided_at = SYSUTCDATETIME() "
            "WHERE case_id = ? AND approval_type = ? AND status = 'pending'",
            case_id, approval_type,
        )
        conn.commit()
    finally:
        conn.close()


def find_approval_by_id(approval_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM dbo.Approvals WHERE approval_id = ?", approval_id)
        return cur.fetchone()
    finally:
        conn.close()


def find_approvals(status: str = None, case_id: str = None):
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if case_id:
        clauses.append("case_id = ?")
        params.append(case_id)
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_COLUMNS}, (SELECT c.case_number FROM dbo.Cases c WHERE c.case_id = dbo.Approvals.case_id) AS case_number "
            f"FROM dbo.Approvals {where}ORDER BY created_at DESC", *params,
        )
        return cur.fetchall()
    finally:
        conn.close()


def find_pending_due_for_reminder(cutoff, max_reminders: int):
    """Pending approvals not (re)notified since `cutoff` and still under the reminder cap."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_COLUMNS} FROM dbo.Approvals "
            "WHERE status = 'pending' AND reminder_count < ? "
            "AND COALESCE(last_reminded_at, created_at) <= ?",
            max_reminders, cutoff,
        )
        return cur.fetchall()
    finally:
        conn.close()


def mark_reminded(approval_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Approvals SET reminder_count = reminder_count + 1, "
            "last_reminded_at = SYSUTCDATETIME() WHERE approval_id = ?",
            approval_id,
        )
        conn.commit()
    finally:
        conn.close()


def decide_pending(approval_id: str, status: str, decided_by: str, decision_note: str) -> bool:
    """Atomically move a pending approval to approved/rejected. False if it was not pending."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Approvals SET status = ?, decided_by = ?, decision_note = ?, "
            "decided_at = SYSUTCDATETIME() WHERE approval_id = ? AND status = 'pending'",
            status, decided_by, decision_note, approval_id,
        )
        updated = cur.rowcount == 1
        conn.commit()
        return updated
    finally:
        conn.close()
