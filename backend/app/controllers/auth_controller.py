import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from app.core import access, audit, security
from app.core.config import settings
from app.core.exceptions import AccountLocked, InvalidCredentials, InvalidToken, RuleViolation
from app.models.auth_schemas import (
    AuthResponse,
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.repositories import user_repository

logger = logging.getLogger("app.auth")

# A refresh token replayed within this window of being rotated is treated as a
# benign race (two tabs / StrictMode refreshing at once), not as token theft.
_REUSE_GRACE_SECONDS = 10


@dataclass
class Session:
    auth: AuthResponse
    refresh_token: str
    persistent: bool

    @property
    def cookie_max_age(self) -> Optional[int]:
        """None -> session cookie (dies with the browser) unless 'remember me'."""
        return _refresh_lifetime(self.persistent) if self.persistent else None


def _refresh_lifetime(persistent: bool) -> int:
    days = settings.REFRESH_TOKEN_REMEMBER_DAYS if persistent else settings.REFRESH_TOKEN_DAYS
    return int(timedelta(days=days).total_seconds())


def _to_user_response(row) -> UserResponse:
    return UserResponse(
        user_id=str(row.user_id),
        username=row.username,
        email=row.email,
        display_name=row.display_name,
        # Shown in the UI as Administrator / User. The real permission set behind it is private to this user.
        role="admin" if row.role == "admin" else "user",
        permissions=sorted(access.permissions_for_role(row.role)),
    )


def _issue_session(row, persistent: bool, family_id: str, user_agent, ip) -> Session:
    access_token, expires_in = security.create_access_token(str(row.user_id), row.username, row.role)
    refresh_token = security.new_refresh_token()
    user_repository.insert_refresh_token(
        user_id=str(row.user_id),
        token_hash=security.hash_refresh_token(refresh_token),
        family_id=family_id,
        persistent=persistent,
        expires_at=security.utcnow() + timedelta(seconds=_refresh_lifetime(persistent)),
        user_agent=user_agent,
        ip_address=ip,
    )
    return Session(
        auth=AuthResponse(access_token=access_token, expires_in=expires_in, user=_to_user_response(row)),
        refresh_token=refresh_token,
        persistent=persistent,
    )


def login(request: LoginRequest, user_agent: Optional[str], ip: Optional[str]) -> Session:
    username = request.username.strip()
    row = user_repository.find_user_by_identifier(username)

    if row is None:
        security.verify_password(request.password, security.DUMMY_PASSWORD_HASH)
        logger.warning("login failed: unknown user %r from %s", username, ip)
        audit.record("auth.login", actor_username=username, outcome="failure", detail={"reason": "unknown_user"}, ip=ip)
        raise InvalidCredentials()

    now = security.utcnow()
    if row.locked_until and row.locked_until > now:
        minutes = max(1, int((row.locked_until - now).total_seconds() // 60) + 1)
        logger.warning("login blocked: %r is locked (from %s)", username, ip)
        audit.record("auth.login", actor_user_id=str(row.user_id), actor_username=row.username, outcome="failure",
                     detail={"reason": "locked"}, ip=ip)
        raise AccountLocked(minutes)

    if not security.verify_password(request.password, row.password_hash):
        will_lock = row.failed_attempts + 1 >= settings.MAX_FAILED_LOGINS
        user_repository.record_failed_login(
            str(row.user_id),
            locked_until=now + timedelta(minutes=settings.LOCKOUT_MINUTES) if will_lock else None,
        )
        logger.warning("login failed: bad password for %r from %s%s", username, ip, " (now locked)" if will_lock else "")
        audit.record("auth.login", actor_user_id=str(row.user_id), actor_username=row.username, outcome="failure",
                     detail={"reason": "bad_password", "locked_now": will_lock}, ip=ip)
        raise InvalidCredentials()

    if not row.is_active:
        logger.warning("login failed: %r is deactivated", username)
        audit.record("auth.login", actor_user_id=str(row.user_id), actor_username=row.username, outcome="failure",
                     detail={"reason": "deactivated"}, ip=ip)
        raise InvalidCredentials()

    user_repository.record_successful_login(str(row.user_id))
    logger.info("login ok: %r from %s", username, ip)
    audit.record("auth.login", actor_user_id=str(row.user_id), actor_username=row.username,
                 detail={"remember_me": request.remember_me}, ip=ip)
    return _issue_session(row, request.remember_me, str(uuid.uuid4()), user_agent, ip)


def refresh(refresh_token: Optional[str], user_agent: Optional[str], ip: Optional[str]) -> Session:
    if not refresh_token:
        raise InvalidToken("Not signed in")

    stored = user_repository.find_refresh_token(security.hash_refresh_token(refresh_token))
    if stored is None:
        raise InvalidToken()

    now = security.utcnow()
    if stored.revoked_at is not None:
        if (now - stored.revoked_at).total_seconds() > _REUSE_GRACE_SECONDS:
            # An already-rotated/logged-out token is being replayed: assume it leaked
            # and end every session in this family.
            user_repository.revoke_token_family(str(stored.family_id))
            logger.warning("refresh token reuse detected for family %s; family revoked", stored.family_id)
            audit.record("auth.refresh_reuse", actor_user_id=str(stored.user_id), outcome="failure",
                         detail={"family": str(stored.family_id)}, ip=ip)
        raise InvalidToken()

    if stored.expires_at <= now:
        raise InvalidToken("Session expired")

    row = user_repository.find_user_by_id(str(stored.user_id))
    if row is None or not row.is_active:
        user_repository.revoke_token_family(str(stored.family_id))
        raise InvalidToken()

    user_repository.revoke_refresh_token(str(stored.token_id))
    return _issue_session(row, bool(stored.persistent), str(stored.family_id), user_agent, ip)


def logout(refresh_token: Optional[str]) -> None:
    """Revokes the whole session family. Never raises: logging out twice is fine."""
    if not refresh_token:
        return
    stored = user_repository.find_refresh_token(security.hash_refresh_token(refresh_token))
    if stored is not None:
        user_repository.revoke_token_family(str(stored.family_id))
        logger.info("logout: family %s revoked", stored.family_id)
        audit.record("auth.logout", actor_user_id=str(stored.user_id))


def get_me(current: CurrentUser) -> UserResponse:
    row = user_repository.find_user_by_id(current.user_id)
    if row is None or not row.is_active:
        raise InvalidToken()
    return _to_user_response(row)


def update_profile(current: CurrentUser, request: UpdateProfileRequest) -> UserResponse:
    user_repository.update_user(current.user_id, request.display_name.strip(), None, None)
    audit.record("profile.update", actor_user_id=current.user_id, actor_username=current.username)
    return get_me(current)


def change_password(
    current: CurrentUser, request: ChangePasswordRequest, user_agent: Optional[str], ip: Optional[str]
) -> Session:
    """Verifies the current password, sets the new one, ends every session, and starts a fresh one here."""
    row = user_repository.find_user_by_id(current.user_id)
    if row is None or not row.is_active:
        raise InvalidToken()
    if not security.verify_password(request.current_password, row.password_hash):
        raise InvalidCredentials("Current password is incorrect")
    if request.new_password == request.current_password:
        raise RuleViolation("New password must be different from the current one.")
    security.validate_password_strength(request.new_password, row.username)

    user_repository.set_password(current.user_id, security.hash_password(request.new_password))
    user_repository.revoke_all_sessions(current.user_id)
    logger.info("password changed: %r from %s", row.username, ip)
    audit.record("auth.password_change", actor_user_id=current.user_id, actor_username=row.username, ip=ip)
    return _issue_session(row, False, str(uuid.uuid4()), user_agent, ip)
