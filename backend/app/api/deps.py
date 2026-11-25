from typing import Callable, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import access, audit
from app.core.exceptions import Forbidden, InvalidToken
from app.core.security import decode_access_token
from app.models.auth_schemas import CurrentUser

_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> CurrentUser:
    """Validates the access token, then confirms against the database (cached for seconds) that the
    user still exists and is active, and takes their CURRENT role. A deactivated user or a changed
    role therefore takes effect almost immediately, not when the token expires."""
    if credentials is None:
        raise InvalidToken("Not authenticated")
    payload = decode_access_token(credentials.credentials)
    state = access.get_user_state(payload["sub"])
    if state is None or not state.is_active:
        raise InvalidToken("Session is no longer valid")
    return CurrentUser(user_id=state.user_id, username=state.username, role=state.role, impersonated_by=payload.get("imp"))


def _deny(request: Request, user: CurrentUser, permission: str) -> None:
    audit.record(
        "authz.denied",
        actor_user_id=user.user_id,
        actor_username=user.username,
        outcome="denied",
        detail={"permission": permission, "method": request.method, "path": request.url.path},
        ip=client_ip(request),
    )
    raise Forbidden()


def require_permission(permission: str) -> Callable[..., CurrentUser]:
    """Guards a single route (or router) behind one explicit permission."""

    def dependency(request: Request, user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not access.has_permission(user.role, permission):
            _deny(request, user, permission)
        return user

    return dependency


def require_method_permissions(read: str, write: str) -> Callable[..., CurrentUser]:
    """Guards a router with different permissions for reading (GET/HEAD) and for changing."""

    def dependency(request: Request, user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        permission = read if request.method in ("GET", "HEAD", "OPTIONS") else write
        if not access.has_permission(user.role, permission):
            _deny(request, user, permission)
        return user

    return dependency


def require_resource(resource: str) -> Callable[..., CurrentUser]:
    """Guards a whole router: GET/HEAD need `<resource>:read`, anything else `<resource>:write`."""

    def dependency(request: Request, user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        action = "read" if request.method in ("GET", "HEAD", "OPTIONS") else "write"
        permission = f"{resource}:{action}"
        if not access.has_permission(user.role, permission):
            _deny(request, user, permission)
        return user

    return dependency
