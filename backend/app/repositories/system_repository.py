from app.db.connection import get_connection


def get_db_overview() -> dict:
    """One round trip that doubles as the database liveness probe."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT "
            "CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(50)) AS server_version, "
            "(SELECT COUNT(*) FROM dbo.Users) AS users, "
            "(SELECT COUNT(*) FROM dbo.RefreshTokens "
            "  WHERE revoked_at IS NULL AND expires_at > SYSUTCDATETIME()) AS active_sessions, "
            "(SELECT COUNT(*) FROM dbo.Cases) AS cases, "
            "(SELECT COUNT(*) FROM dbo.Cases WHERE status = 'open') AS open_cases, "
            "(SELECT COUNT(*) FROM dbo.SchemaMigrations) AS migrations_applied"
        )
        row = cur.fetchone()
        return {
            "server_version": row.server_version,
            "users": row.users,
            "active_sessions": row.active_sessions,
            "cases": row.cases,
            "open_cases": row.open_cases,
            "migrations_applied": row.migrations_applied,
        }
    finally:
        conn.close()
