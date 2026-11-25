"""Live authorization lookups.

The access token only says WHO the caller is. What they may do is resolved here, from the
database, on every request (behind a short cache), so that changing a role's permissions,
moving a user to another role, or deactivating a user takes effect within seconds instead
of when their token happens to expire. Our own writes invalidate the cache immediately;
the TTLs bound staleness if several server processes run.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.core.permissions import ADMIN_ROLE, ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, SYSTEM_ROLES
from app.repositories import role_repository, user_repository

logger = logging.getLogger("app.access")

ROLE_TTL_SECONDS = 30
USER_TTL_SECONDS = 15


@dataclass(frozen=True)
class UserState:
    user_id: str
    username: str
    role: str
    is_active: bool


_lock = threading.Lock()
_roles: dict[str, frozenset[str]] = {}
_roles_loaded_at = 0.0
_users: dict[str, tuple[float, Optional[UserState]]] = {}


def invalidate() -> None:
    """Drop every cached role and user (call after any change to roles, permissions or users)."""
    global _roles_loaded_at
    with _lock:
        _roles.clear()
        _users.clear()
        _roles_loaded_at = 0.0


def _load_roles() -> dict[str, frozenset[str]]:
    global _roles_loaded_at
    with _lock:
        if _roles and time.monotonic() - _roles_loaded_at < ROLE_TTL_SECONDS:
            return _roles
    loaded = {name: frozenset(perms) for name, perms in role_repository.find_permissions_by_role().items()}
    with _lock:
        _roles.clear()
        _roles.update(loaded)
        _roles_loaded_at = time.monotonic()
        return _roles


def permissions_for_role(role: str) -> frozenset[str]:
    if role == ADMIN_ROLE:
        return ALL_PERMISSIONS  # the admin role can never be configured into a lockout
    # Unknown permission strings (e.g. left over from an older catalog) grant nothing.
    return _load_roles().get(role, frozenset()) & ALL_PERMISSIONS


def has_permission(role: str, permission: str) -> bool:
    return permission in permissions_for_role(role)


def get_user_state(user_id: str) -> Optional[UserState]:
    key = user_id.lower()
    now = time.monotonic()
    with _lock:
        hit = _users.get(key)
        if hit and now - hit[0] < USER_TTL_SECONDS:
            return hit[1]
    row = user_repository.find_user_by_id(user_id)
    state = (
        UserState(str(row.user_id), row.username, row.role, bool(row.is_active)) if row is not None else None
    )
    with _lock:
        _users[key] = (now, state)
    return state


def sync_system_roles() -> None:
    """Run at startup: admin always gets everything; other built-in roles get their defaults once."""
    for name in SYSTEM_ROLES:
        if name == ADMIN_ROLE:
            role_repository.replace_permissions(name, ALL_PERMISSIONS)
        elif role_repository.apply_defaults_once(name, DEFAULT_ROLE_PERMISSIONS[name]):
            logger.info("seeded default permissions for role %r", name)
    invalidate()
