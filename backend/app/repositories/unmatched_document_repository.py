import uuid

from app.db.connection import get_connection

_COLUMNS = ("document_id, from_email, vendor_name, subject, summary, file_names, payload, status, case_id, handled_by, handled_at, note, created_at")


def insert_document(from_email: str, vendor_name: str | None, subject: str, summary: str, file_names: str, payload: str) -> str:
    document_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.cursor().execute(
            "INSERT INTO dbo.UnmatchedDocuments (document_id, from_email, vendor_name, subject, summary, file_names, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            document_id, from_email, vendor_name, subject, summary, file_names, payload,
        )
        conn.commit()
        return document_id
    finally:
        conn.close()


def find_open() -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM dbo.UnmatchedDocuments WHERE status = 'open' ORDER BY created_at DESC")
        return cur.fetchall()
    finally:
        conn.close()


def find_by_id(document_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLUMNS} FROM dbo.UnmatchedDocuments WHERE document_id = ?", document_id)
        return cur.fetchone()
    finally:
        conn.close()


def mark_handled(document_id: str, status: str, handled_by: str, case_id: str | None, note: str | None) -> bool:
    """Only a document that is still open can be handled (two people clicking at once: one wins)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.UnmatchedDocuments SET status = ?, handled_by = ?, handled_at = SYSUTCDATETIME(), case_id = ?, note = ? "
            "WHERE document_id = ? AND status = 'open'",
            status, handled_by, case_id, note, document_id,
        )
        changed = cur.rowcount
        conn.commit()
        return changed > 0
    finally:
        conn.close()
