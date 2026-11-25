from datetime import datetime
from typing import Optional

from app.db.connection import get_connection


def insert_entry(
    actor_user_id: Optional[str],
    actor_username: Optional[str],
    action: str,
    outcome: str,
    target_type: Optional[str],
    target_id: Optional[str],
    detail: Optional[str],
    ip_address: Optional[str],
) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.AuditLog "
            "(actor_user_id, actor_username, action, outcome, target_type, target_id, detail, ip_address) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            actor_user_id, actor_username, action, outcome, target_type, target_id, detail, ip_address,
        )
        conn.commit()
    finally:
        conn.close()


def _where(action: Optional[str], outcome: Optional[str], search: Optional[str], since: Optional[datetime]):
    clauses, params = [], []
    if action:
        clauses.append("action LIKE ?")
        params.append(f"{action}%")
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    if search:
        clauses.append("(actor_username LIKE ? OR target_id LIKE ? OR detail LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def find_entries(
    limit: int, offset: int, action: Optional[str], outcome: Optional[str], search: Optional[str], since: Optional[datetime]
):
    where, params = _where(action, outcome, search, since)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM dbo.AuditLog{where}", *params)
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT audit_id, actor_user_id, actor_username, action, outcome, target_type, target_id, "
            f"detail, ip_address, created_at FROM dbo.AuditLog{where} "
            "ORDER BY created_at DESC, audit_id DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            *params, offset, limit,
        )
        return total, cur.fetchall()
    finally:
        conn.close()
