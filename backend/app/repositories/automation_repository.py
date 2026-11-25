from app.db.connection import get_connection


def get_setting(key: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT setting_value, updated_at, updated_by FROM dbo.SystemSettings WHERE setting_key = ?", key,
        )
        return cur.fetchone()
    finally:
        conn.close()


def claim_setting(key: str, value: str, updated_by: str | None) -> bool:
    """Set the key to `value` only if it holds something DIFFERENT, in one statement. True for the one caller that changed it, False for anyone
    else (the value was already there). Used to claim "this summary was sent for this period" so it is sent once, however many copies run."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.SystemSettings SET setting_value = ?, updated_at = SYSUTCDATETIME(), updated_by = ? WHERE setting_key = ? AND setting_value <> ?",
            value, updated_by, key, value,
        )
        won = cur.rowcount == 1
        if not won:
            cur.execute(
                "INSERT INTO dbo.SystemSettings (setting_key, setting_value, updated_by) "
                "SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM dbo.SystemSettings WHERE setting_key = ?)",
                key, value, updated_by, key,
            )
            won = cur.rowcount == 1
        conn.commit()
        return won
    finally:
        conn.close()


def set_setting(key: str, value: str, updated_by: str | None) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.SystemSettings SET setting_value = ?, updated_at = SYSUTCDATETIME(), updated_by = ? "
            "WHERE setting_key = ?",
            value, updated_by, key,
        )
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO dbo.SystemSettings (setting_key, setting_value, updated_by) VALUES (?, ?, ?)",
                key, value, updated_by,
            )
        conn.commit()
    finally:
        conn.close()


def list_settings(prefix: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT setting_key, setting_value, updated_at, updated_by FROM dbo.SystemSettings WHERE setting_key LIKE ?",
            prefix + "%",
        )
        return cur.fetchall()
    finally:
        conn.close()


def delete_setting(key: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.SystemSettings WHERE setting_key = ?", key)
        conn.commit()
    finally:
        conn.close()


def try_acquire_lease(name: str, holder: str, ttl_seconds: int) -> bool:
    """Take (or renew) the named lease if it is free, expired, or already ours. Atomic in SQL,
    so only one process can hold it. A holder that dies simply stops renewing and the lease expires."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.WorkerLeases SET holder = ?, expires_at = DATEADD(second, ?, SYSUTCDATETIME()) "
            "WHERE name = ? AND (holder = ? OR expires_at < SYSUTCDATETIME())",
            holder, ttl_seconds, name, holder,
        )
        if cur.rowcount == 1:
            conn.commit()
            return True
        cur.execute(
            "INSERT INTO dbo.WorkerLeases (name, holder, expires_at) "
            "SELECT ?, ?, DATEADD(second, ?, SYSUTCDATETIME()) "
            "WHERE NOT EXISTS (SELECT 1 FROM dbo.WorkerLeases WHERE name = ?)",
            name, holder, ttl_seconds, name,
        )
        acquired = cur.rowcount == 1
        conn.commit()
        return acquired
    except Exception:
        # Lost an insert race with another instance: it holds the lease.
        conn.rollback()
        return False
    finally:
        conn.close()
