from app.db.connection import get_connection


def insert_link(link_id: str, approval_id: str, user_id: str, token_hash: str, expires_at) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.ApprovalLinks (link_id, approval_id, user_id, token_hash, expires_at) VALUES (?, ?, ?, ?, ?)",
            link_id, approval_id, user_id, token_hash, expires_at,
        )
        conn.commit()
    finally:
        conn.close()


def revoke_for(approval_id: str, user_id: str | None = None) -> None:
    """Older links stop working: for one person (a fresh email replaces their old one) or for everybody (the approval was decided)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        if user_id:
            cur.execute("UPDATE dbo.ApprovalLinks SET revoked_at = SYSUTCDATETIME() WHERE approval_id = ? AND user_id = ? AND used_at IS NULL AND revoked_at IS NULL", approval_id, user_id)
        else:
            cur.execute("UPDATE dbo.ApprovalLinks SET revoked_at = SYSUTCDATETIME() WHERE approval_id = ? AND used_at IS NULL AND revoked_at IS NULL", approval_id)
        conn.commit()
    finally:
        conn.close()


def find_by_hash(token_hash: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT link_id, approval_id, user_id, created_at, expires_at, used_at, used_action, revoked_at "
            "FROM dbo.ApprovalLinks WHERE token_hash = ?", token_hash,
        )
        return cur.fetchone()
    finally:
        conn.close()


def revoke_for_user(user_id: str) -> int:
    """Every unused link made for this person stops working (they were deactivated or deleted). Returns how many."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.ApprovalLinks SET revoked_at = SYSUTCDATETIME() WHERE user_id = ? AND used_at IS NULL AND revoked_at IS NULL", user_id)
        count = cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def mark_used(link_id: str, action: str, ip: str | None) -> bool:
    """Use the link. Atomic: of two taps at once, only one gets True."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.ApprovalLinks SET used_at = SYSUTCDATETIME(), used_action = ?, used_ip = ? "
            "WHERE link_id = ? AND used_at IS NULL AND revoked_at IS NULL AND expires_at >= SYSUTCDATETIME()",
            action, (ip or "")[:64], link_id,
        )
        done = cur.rowcount == 1
        conn.commit()
        return done
    finally:
        conn.close()
