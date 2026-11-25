import uuid
from typing import Iterable, Optional

from app.db.connection import get_connection


def find_all_roles():
    """Every role with how many users hold it."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.role_id, r.name, r.display_name, r.description, r.is_system, r.created_at, "
            "(SELECT COUNT(*) FROM dbo.Users u WHERE u.role = r.name) AS user_count "
            "FROM dbo.Roles r ORDER BY r.is_system DESC, r.display_name ASC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def find_role(name: str):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.role_id, r.name, r.display_name, r.description, r.is_system, r.defaults_applied, "
            "r.created_at, (SELECT COUNT(*) FROM dbo.Users u WHERE u.role = r.name) AS user_count "
            "FROM dbo.Roles r WHERE r.name = ?",
            name,
        )
        return cur.fetchone()
    finally:
        conn.close()


def find_permissions_by_role() -> dict[str, set[str]]:
    """{role name: {permission, ...}} for every role (one query, used to fill caches)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.name, rp.permission FROM dbo.Roles r "
            "LEFT JOIN dbo.RolePermissions rp ON rp.role_id = r.role_id"
        )
        result: dict[str, set[str]] = {}
        for row in cur.fetchall():
            perms = result.setdefault(row.name, set())
            if row.permission:
                perms.add(row.permission)
        return result
    finally:
        conn.close()


def find_permissions_for_role(name: str) -> set[str]:
    return find_permissions_by_role().get(name, set())


def create_role(name: str, display_name: str, description: Optional[str], permissions: Iterable[str]) -> None:
    role_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO dbo.Roles (role_id, name, display_name, description, is_system, defaults_applied) "
            "VALUES (?, ?, ?, ?, 0, 1)",
            role_id, name, display_name, description,
        )
        _insert_permissions(cur, role_id, permissions)
        conn.commit()
    finally:
        conn.close()


def update_role(
    name: str, display_name: Optional[str], description: Optional[str], permissions: Optional[Iterable[str]]
) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role_id FROM dbo.Roles WHERE name = ?", name)
        row = cur.fetchone()
        if row is None:
            return
        sets, params = [], []
        if display_name is not None:
            sets.append("display_name = ?")
            params.append(display_name)
        if description is not None:
            sets.append("description = ?")
            params.append(description or None)
        if sets:
            cur.execute(
                f"UPDATE dbo.Roles SET {', '.join(sets)}, updated_at = SYSUTCDATETIME() WHERE role_id = ?",
                *params, row.role_id,
            )
        if permissions is not None:
            cur.execute("DELETE FROM dbo.RolePermissions WHERE role_id = ?", row.role_id)
            _insert_permissions(cur, str(row.role_id), permissions)
            cur.execute("UPDATE dbo.Roles SET updated_at = SYSUTCDATETIME() WHERE role_id = ?", row.role_id)
        conn.commit()
    finally:
        conn.close()


def delete_role(name: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.Roles WHERE name = ? AND is_system = 0", name)
        conn.commit()
    finally:
        conn.close()


def apply_defaults_once(name: str, permissions: Iterable[str]) -> bool:
    """Seeds a built-in role's default permissions the first time only. True if it seeded."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT role_id, defaults_applied FROM dbo.Roles WHERE name = ?", name)
        row = cur.fetchone()
        if row is None or row.defaults_applied:
            return False
        cur.execute("DELETE FROM dbo.RolePermissions WHERE role_id = ?", row.role_id)
        _insert_permissions(cur, str(row.role_id), permissions)
        cur.execute("UPDATE dbo.Roles SET defaults_applied = 1 WHERE role_id = ?", row.role_id)
        conn.commit()
        return True
    finally:
        conn.close()


def replace_permissions(name: str, permissions: Iterable[str]) -> None:
    update_role(name, None, None, permissions)


def _insert_permissions(cur, role_id: str, permissions: Iterable[str]) -> None:
    for permission in sorted(set(permissions)):
        cur.execute("INSERT INTO dbo.RolePermissions (role_id, permission) VALUES (?, ?)", role_id, permission)
