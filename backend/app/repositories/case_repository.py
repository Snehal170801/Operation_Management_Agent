import json
from datetime import datetime, timezone

import pyodbc

from app.core.case_number import format_case_number
from app.core.live import hub

from app.db.connection import get_connection


def _next_case_number(cur, year: int) -> str:
    """The next REQ-<year>-<n>. One UPDATE both increments and returns the counter, so concurrent requests
    queue on the row lock and each gets a different number; it commits (or rolls back) with the case."""
    for _ in range(3):
        cur.execute("UPDATE dbo.CaseCounters SET last_no = last_no + 1 OUTPUT INSERTED.last_no WHERE [year] = ?", year)
        row = cur.fetchone()
        if row is not None:
            return format_case_number(year, row[0])
        try:  # first case of a new year
            cur.execute("INSERT INTO dbo.CaseCounters ([year], last_no) VALUES (?, 1)", year)
            return format_case_number(year, 1)
        except pyodbc.IntegrityError:
            continue  # another request created the row first: take the next number from it
    raise RuntimeError("could not allocate a case number")


def insert_case(case_id: str, requester_id: str) -> str:
    """Creates the case and returns its case number."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        number = _next_case_number(cur, datetime.now(timezone.utc).year)
        cur.execute(
            "INSERT INTO dbo.Cases (case_id, requester_id, stage, status, case_number) "
            "VALUES (?, ?, 'created', 'open', ?)",
            case_id, requester_id, number,
        )
        conn.commit()
        return number
    finally:
        conn.close()


def find_case_by_id(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT case_id, case_number, requester_id, stage, status, summary, created_at, updated_at "
            "FROM dbo.Cases WHERE case_id = ?",
            case_id,
        )
        return cur.fetchone()
    finally:
        conn.close()


def find_all_cases(requester_id: str | None = None):
    conn = get_connection()
    try:
        cur = conn.cursor()
        where = "WHERE LOWER(c.requester_id) = LOWER(?) " if requester_id else ""
        cur.execute(
            "SELECT c.case_id, c.case_number, c.requester_id, c.stage, c.status, "
            "c.created_at, c.updated_at, agg.item_count, agg.total_quantity, agg.items_summary, agg.urgent, agg.needed_by "
            "FROM dbo.Cases c "
            "LEFT JOIN ("
            "    SELECT pr.case_id, COUNT(pri.item_id) AS item_count, SUM(pri.quantity) AS total_quantity, "
            "           MAX(CAST(pr.urgent AS INT)) AS urgent, MAX(pr.needed_by) AS needed_by, "
            "           STRING_AGG(CONCAT(pri.description, ' (', pri.quantity, ')'), ', ') "
            "               WITHIN GROUP (ORDER BY pri.created_at) AS items_summary "
            "    FROM dbo.PurchaseRequests pr "
            "    JOIN dbo.PurchaseRequestItems pri ON pri.purchase_request_id = pr.purchase_request_id "
            "    GROUP BY pr.case_id"
            ") agg ON agg.case_id = c.case_id "
            + where +
            "ORDER BY c.created_at DESC",
            *([requester_id] if requester_id else []),
        )
        return cur.fetchall()
    finally:
        conn.close()


def find_open_case_ids_by_stage(stage: str, idle_since=None) -> list[str]:
    """Open cases in a stage; with `idle_since`, only those untouched since then."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        if idle_since is None:
            cur.execute(
                "SELECT case_id FROM dbo.Cases WHERE stage = ? AND status = 'open' ORDER BY created_at ASC",
                stage,
            )
        else:
            cur.execute(
                "SELECT case_id FROM dbo.Cases WHERE stage = ? AND status = 'open' AND updated_at <= ? "
                "ORDER BY created_at ASC",
                stage, idle_since,
            )
        return [str(row.case_id) for row in cur.fetchall()]
    finally:
        conn.close()


def find_recent_duplicate(requester_id: str, raw_request: str, since) -> str | None:
    """The newest case this person opened with exactly this request text since `since`, if any."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP 1 c.case_id FROM dbo.Cases c "
            "JOIN dbo.PurchaseRequests pr ON pr.case_id = c.case_id "
            "WHERE LOWER(c.requester_id) = LOWER(?) AND c.created_at >= ? "
            "AND CAST(pr.raw_request AS NVARCHAR(MAX)) = ? ORDER BY c.created_at DESC",
            requester_id, since, raw_request,
        )
        row = cur.fetchone()
        return str(row.case_id) if row else None
    finally:
        conn.close()


def count_cases_since(requester_id: str, since) -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM dbo.Cases WHERE LOWER(requester_id) = LOWER(?) AND created_at >= ?",
            requester_id, since,
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


def update_case_stage_and_status(case_id: str, stage: str, status: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Cases SET stage = ?, status = ?, updated_at = SYSUTCDATETIME() WHERE case_id = ?",
            stage, status, case_id,
        )
        conn.commit()
    finally:
        conn.close()


def update_case_stage(case_id: str, stage: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Cases SET stage = ?, updated_at = SYSUTCDATETIME() WHERE case_id = ?",
            stage, case_id,
        )
        conn.commit()
    finally:
        conn.close()


def insert_event(case_id: str, event_type: str, agent_name: str = None, payload: dict = None) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.CaseEvents (case_id, event_type, agent_name, payload) "
            "VALUES (?, ?, ?, ?)",
            case_id, event_type, agent_name, json.dumps(payload or {}),
        )
        conn.commit()
    finally:
        conn.close()
    hub.publish(case_id, event_type)  # tell the open pages, now that it is saved


def find_events_of_types(event_types: tuple[str, ...], since=None):
    """Events of the given kinds across every case (optionally only since a time), oldest first."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        marks = ", ".join("?" for _ in event_types)
        cur.execute(
            f"SELECT case_id, event_type, payload, created_at FROM dbo.CaseEvents WHERE event_type IN ({marks})"
            + (" AND created_at >= ?" if since is not None else "") + " ORDER BY created_at ASC",
            *event_types, *([since] if since is not None else []),
        )
        return cur.fetchall()
    finally:
        conn.close()


def find_events_by_case_id(case_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT event_id, event_type, agent_name, payload, created_at "
            "FROM dbo.CaseEvents WHERE case_id = ? ORDER BY created_at ASC",
            case_id,
        )
        return cur.fetchall()
    finally:
        conn.close()
