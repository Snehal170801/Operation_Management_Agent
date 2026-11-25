from app.db.connection import get_connection


def known_hashes(case_id: str) -> set[str]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT file_hash FROM dbo.ReadFiles WHERE case_id = ?", case_id)
        return {r.file_hash.lower() for r in cur.fetchall()}
    finally:
        conn.close()


def find_all(limit: int = 5000):
    """Every file the system has read, newest first (name and when; for the document store)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT TOP ({int(limit)}) case_id, file_hash, file_name, first_read_at FROM dbo.ReadFiles WHERE COALESCE(file_name, '') <> '(email text)' ORDER BY first_read_at DESC")
        return cur.fetchall()
    finally:
        conn.close()


def remember(case_id: str, files: list[tuple[str, str]]) -> None:
    """Safe to repeat: a hash already remembered for the case is left alone."""
    if not files:
        return
    conn = get_connection()
    try:
        cur = conn.cursor()
        for file_hash, name in files:
            cur.execute(
                "IF NOT EXISTS (SELECT 1 FROM dbo.ReadFiles WHERE case_id = ? AND file_hash = ?) "
                "INSERT INTO dbo.ReadFiles (case_id, file_hash, file_name) VALUES (?, ?, ?)",
                case_id, file_hash, case_id, file_hash, name[:260],
            )
        conn.commit()
    finally:
        conn.close()
