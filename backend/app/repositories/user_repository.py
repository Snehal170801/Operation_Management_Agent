import uuid
from datetime import datetime
from typing import Optional

from app.db.connection import get_connection

_USER_COLUMNS = (
    "user_id, username, display_name, password_hash, role, is_active, "
    "failed_attempts, locked_until, last_login_at, created_at, email, on_leave_from, on_leave_until, delegate_user_id"
)


def find_user_by_username(username: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_COLUMNS} FROM dbo.Users WHERE username = ?", username)
        return cur.fetchone()
    finally:
        conn.close()


def find_user_by_identifier(identifier: str):
    """Sign-in / reset lookup: the identifier is the email (or legacy username). Case-insensitive."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_USER_COLUMNS} FROM dbo.Users WHERE username = ? OR email = ?",
            identifier, identifier,
        )
        return cur.fetchone()
    finally:
        conn.close()


def find_user_by_email(email: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_COLUMNS} FROM dbo.Users WHERE email = ?", email)
        return cur.fetchone()
    finally:
        conn.close()


def find_user_by_id(user_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_COLUMNS} FROM dbo.Users WHERE user_id = ?", user_id)
        return cur.fetchone()
    finally:
        conn.close()


def upsert_user(
    username: str, password_hash: str, role: str, display_name: Optional[str], email: Optional[str] = None
) -> bool:
    """Creates the user, or resets password/role/active/lockout if it exists. Returns True if created."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM dbo.Users WHERE username = ?", username)
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE dbo.Users SET password_hash = ?, role = ?, display_name = ?, email = COALESCE(?, email), "
                "is_active = 1, failed_attempts = 0, locked_until = NULL, updated_at = SYSUTCDATETIME() "
                "WHERE user_id = ?",
                password_hash, role, display_name, email, row.user_id,
            )
            # A password reset ends every existing session.
            cur.execute(
                "UPDATE dbo.RefreshTokens SET revoked_at = SYSUTCDATETIME() "
                "WHERE user_id = ? AND revoked_at IS NULL",
                row.user_id,
            )
        else:
            cur.execute(
                "INSERT INTO dbo.Users (user_id, username, display_name, password_hash, role, email) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                str(uuid.uuid4()), username, display_name, password_hash, role, email,
            )
        conn.commit()
        return row is None
    finally:
        conn.close()


def record_failed_login(user_id: str, locked_until: Optional[datetime]) -> None:
    """Counts a failure; when locked_until is given, locks the account and resets the counter."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        if locked_until is not None:
            cur.execute(
                "UPDATE dbo.Users SET failed_attempts = 0, locked_until = ?, "
                "updated_at = SYSUTCDATETIME() WHERE user_id = ?",
                locked_until, user_id,
            )
        else:
            cur.execute(
                "UPDATE dbo.Users SET failed_attempts = failed_attempts + 1, "
                "updated_at = SYSUTCDATETIME() WHERE user_id = ?",
                user_id,
            )
        conn.commit()
    finally:
        conn.close()


def record_successful_login(user_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Users SET failed_attempts = 0, locked_until = NULL, "
            "last_login_at = SYSUTCDATETIME(), updated_at = SYSUTCDATETIME() WHERE user_id = ?",
            user_id,
        )
        conn.commit()
    finally:
        conn.close()


# ---------- refresh tokens ----------

def insert_refresh_token(
    user_id: str,
    token_hash: str,
    family_id: str,
    persistent: bool,
    expires_at: datetime,
    user_agent: Optional[str],
    ip_address: Optional[str],
) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.RefreshTokens "
            "(token_id, user_id, token_hash, family_id, persistent, expires_at, user_agent, ip_address) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            str(uuid.uuid4()), user_id, token_hash, family_id, 1 if persistent else 0,
            expires_at, (user_agent or "")[:300] or None, ip_address,
        )
        conn.commit()
    finally:
        conn.close()


def find_refresh_token(token_hash: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT token_id, user_id, family_id, persistent, expires_at, revoked_at "
            "FROM dbo.RefreshTokens WHERE token_hash = ?",
            token_hash,
        )
        return cur.fetchone()
    finally:
        conn.close()


def revoke_refresh_token(token_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.RefreshTokens SET revoked_at = SYSUTCDATETIME() "
            "WHERE token_id = ? AND revoked_at IS NULL",
            token_id,
        )
        conn.commit()
    finally:
        conn.close()


def revoke_token_family(family_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.RefreshTokens SET revoked_at = SYSUTCDATETIME() "
            "WHERE family_id = ? AND revoked_at IS NULL",
            family_id,
        )
        conn.commit()
    finally:
        conn.close()


# ---------- user management ----------

def find_all_users():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_USER_COLUMNS} FROM dbo.Users ORDER BY username ASC")
        return cur.fetchall()
    finally:
        conn.close()


def create_user(
    username: str,
    password_hash: str,
    role: str,
    display_name: Optional[str],
    email: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    user_id = user_id or str(uuid.uuid4())
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.Users (user_id, username, display_name, password_hash, role, email) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            user_id, username, display_name, password_hash, role, email,
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


def set_leave(user_id: str, on_leave_from, on_leave_until, delegate_user_id: Optional[str]) -> None:
    """Leave dates and the backup approver, set together (None clears each)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.Users SET on_leave_from = ?, on_leave_until = ?, delegate_user_id = ?, updated_at = SYSUTCDATETIME() WHERE user_id = ?",
                    on_leave_from, on_leave_until, delegate_user_id or None, user_id)
        conn.commit()
    finally:
        conn.close()


def update_user(
    user_id: str,
    display_name: Optional[str],
    role: Optional[str],
    is_active: Optional[bool],
    email: Optional[str] = None,
) -> None:
    """Only the provided (non-None) fields change. An empty email clears it."""
    sets, params = [], []
    if email is not None:
        sets.append("email = ?")
        params.append(email or None)
    if display_name is not None:
        sets.append("display_name = ?")
        params.append(display_name or None)
    if role is not None:
        sets.append("role = ?")
        params.append(role)
    if is_active is not None:
        sets.append("is_active = ?")
        params.append(1 if is_active else 0)
    if not sets:
        return
    sets.append("updated_at = SYSUTCDATETIME()")
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE dbo.Users SET {', '.join(sets)} WHERE user_id = ?", *params, user_id)
        conn.commit()
    finally:
        conn.close()


def set_password(user_id: str, password_hash: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Users SET password_hash = ?, failed_attempts = 0, locked_until = NULL, "
            "updated_at = SYSUTCDATETIME() WHERE user_id = ?",
            password_hash, user_id,
        )
        conn.commit()
    finally:
        conn.close()


def unlock_user(user_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Users SET failed_attempts = 0, locked_until = NULL, "
            "updated_at = SYSUTCDATETIME() WHERE user_id = ?",
            user_id,
        )
        conn.commit()
    finally:
        conn.close()


def count_active_admins() -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM dbo.Users WHERE role = 'admin' AND is_active = 1")
        return cur.fetchone()[0]
    finally:
        conn.close()


def delete_user(user_id: str) -> None:
    """Permanently removes the user and the sign-in records that point at them (sessions, reset codes).
    Cases, approvals and the audit log only store the person's name as text, so that history stays."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.RefreshTokens WHERE user_id = ?", user_id)
        cur.execute("DELETE FROM dbo.PasswordResetOtps WHERE user_id = ?", user_id)
        cur.execute("DELETE FROM dbo.Users WHERE user_id = ?", user_id)
        conn.commit()
    finally:
        conn.close()


def revoke_all_sessions(user_id: str) -> None:
    """Signs the user out everywhere (all refresh tokens revoked)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.RefreshTokens SET revoked_at = SYSUTCDATETIME() "
            "WHERE user_id = ? AND revoked_at IS NULL",
            user_id,
        )
        conn.commit()
    finally:
        conn.close()


# ---------- password-reset one-time codes ----------

def insert_otp(user_id: str, otp_hash: str, expires_at: datetime, ip_address: Optional[str]) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.PasswordResetOtps (otp_id, user_id, otp_hash, expires_at, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            str(uuid.uuid4()), user_id, otp_hash, expires_at, ip_address,
        )
        conn.commit()
    finally:
        conn.close()


def find_latest_otp(user_id: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TOP 1 otp_id, otp_hash, expires_at, attempts, used_at, created_at "
            "FROM dbo.PasswordResetOtps WHERE user_id = ? ORDER BY created_at DESC",
            user_id,
        )
        return cur.fetchone()
    finally:
        conn.close()


def count_otps_since(user_id: str, since: datetime) -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM dbo.PasswordResetOtps WHERE user_id = ? AND created_at >= ?",
            user_id, since,
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


def increment_otp_attempts(otp_id: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE dbo.PasswordResetOtps SET attempts = attempts + 1 WHERE otp_id = ?", otp_id)
        conn.commit()
    finally:
        conn.close()


def invalidate_otps(user_id: str) -> None:
    """Marks every unused code for the user as used (consumed on success, or superseded by a new one)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.PasswordResetOtps SET used_at = SYSUTCDATETIME() "
            "WHERE user_id = ? AND used_at IS NULL",
            user_id,
        )
        conn.commit()
    finally:
        conn.close()


def find_active_users_with_permission(permission: str):
    """Active users with an email address who hold `permission` (admins hold everything).

    Used to decide who gets alert emails, so it follows what people can actually DO rather than a
    job title.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_USER_COLUMNS} FROM dbo.Users u "
            "WHERE u.is_active = 1 AND u.email IS NOT NULL AND ("
            "  u.role = 'admin' OR EXISTS ("
            "    SELECT 1 FROM dbo.Roles r JOIN dbo.RolePermissions rp ON rp.role_id = r.role_id "
            "    WHERE r.name = u.role AND rp.permission = ?))",
            permission,
        )
        return cur.fetchall()
    finally:
        conn.close()
