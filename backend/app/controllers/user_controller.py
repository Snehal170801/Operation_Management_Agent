import logging
import uuid
from datetime import date
from typing import Optional

from app.agents import notification_agent
from app.core import access, approver_leave, audit, security
from app.core.config import settings
from app.core.exceptions import EmailTaken, InvalidInput, RuleViolation, UserNotFound, UsernameTaken
from app.core.permissions import (
    ADMIN_ROLE,
    ALL_PERMISSIONS,
    CATALOG,
    DEPARTMENTS,
    LOCKOUT_PERMISSIONS,
    is_private_role,
    private_role_name,
)
from app.models.auth_schemas import (
    AccessLevel,
    CreateUserRequest,
    CurrentUser,
    DepartmentInfo,
    ManagedUserResponse,
    OpenedAccount,
    PermissionGroup,
    PermissionInfo,
    ResetPasswordRequest,
    UpdateUserRequest,
)
from app.orchestrator import case_pipeline
from app.repositories import role_repository, user_repository

logger = logging.getLogger("app.users")


# ---------- responses ----------

def _permissions_of(row, by_role: dict[str, set[str]]) -> list[str]:
    if row.role == ADMIN_ROLE:
        return sorted(ALL_PERMISSIONS)
    return sorted(by_role.get(row.role, set()) & ALL_PERMISSIONS)


def _to_response(row, by_role: dict[str, set[str]], names: dict[str, str] | None = None) -> ManagedUserResponse:
    now = security.utcnow()
    delegate = str(row.delegate_user_id) if getattr(row, "delegate_user_id", None) else None
    return ManagedUserResponse(
        user_id=str(row.user_id),
        username=row.username,
        email=row.email,
        display_name=row.display_name,
        is_admin=row.role == ADMIN_ROLE,
        permissions=_permissions_of(row, by_role),
        is_active=bool(row.is_active),
        is_locked=bool(row.locked_until and row.locked_until > now),
        last_login_at=row.last_login_at,
        created_at=row.created_at,
        on_leave_from=getattr(row, "on_leave_from", None),
        on_leave_until=getattr(row, "on_leave_until", None),
        on_leave_now=approver_leave.on_leave({"on_leave_from": getattr(row, "on_leave_from", None), "on_leave_until": getattr(row, "on_leave_until", None)}, notification_agent.today_india()),
        delegate_user_id=delegate,
        delegate_name=(names or {}).get((delegate or "").lower()),
    )


def _names(rows) -> dict[str, str]:
    """{user_id: display name} for the people these rows name as their backup (one lookup each, only when someone has one)."""
    wanted = {str(r.delegate_user_id).lower() for r in rows if getattr(r, "delegate_user_id", None)}
    if not wanted:
        return {}
    known = {str(r.user_id).lower(): r for r in rows}
    out = {}
    for key in wanted:
        person = known.get(key) or user_repository.find_user_by_id(key)
        if person is not None:
            out[key] = person.display_name or person.username
    return out


def _apply_leave(request: UpdateUserRequest, target, is_self: bool) -> dict | None:
    """Leave dates and the backup approver, when the request sends them (null clears). Returns what changed, or None. The backup must be someone
    else who is active and may approve, so an approval never goes to a person who cannot decide it."""
    sent = request.model_fields_set & {"on_leave_from", "on_leave_until", "delegate_user_id"}
    if not sent:
        return None
    start = request.on_leave_from if "on_leave_from" in sent else getattr(target, "on_leave_from", None)
    end = request.on_leave_until if "on_leave_until" in sent else getattr(target, "on_leave_until", None)
    delegate = (request.delegate_user_id or None) if "delegate_user_id" in sent else (str(target.delegate_user_id) if getattr(target, "delegate_user_id", None) else None)
    approver_leave.check_leave(start, end)
    if delegate:
        if delegate.lower() == str(target.user_id).lower():
            raise InvalidInput("A person cannot be their own backup.")
        backup = user_repository.find_user_by_id(delegate)
        if backup is None or not backup.is_active:
            raise InvalidInput("The backup approver must be an active user.")
        if backup.role != ADMIN_ROLE and not access.has_permission(backup.role, "approvals:write"):
            raise InvalidInput("The backup approver must be someone who can approve orders.")
    user_repository.set_leave(str(target.user_id), start, end, delegate)
    return {"on_leave_from": str(start) if start else None, "on_leave_until": str(end) if end else None, "delegate_user_id": delegate}


def _get_or_404(user_id: str):
    row = user_repository.find_user_by_id(user_id)
    if row is None:
        raise UserNotFound()
    return row


def _fresh(user_id: str) -> ManagedUserResponse:
    row = _get_or_404(user_id)
    return _to_response(row, role_repository.find_permissions_by_role(), _names([row]))


def list_users() -> list[ManagedUserResponse]:
    by_role = role_repository.find_permissions_by_role()
    rows = user_repository.find_all_users()
    names = _names(rows)
    return [_to_response(r, by_role, names) for r in rows]


def departments() -> list[DepartmentInfo]:
    return [DepartmentInfo(key=d.key, label=d.label, agent=d.agent, handles=d.handles, permissions=list(d.permissions)) for d in DEPARTMENTS]


def catalog() -> list[PermissionGroup]:
    """Everything that can be ticked, grouped by module, for the Users screen."""
    return [
        PermissionGroup(
            resource=g.resource,
            label=g.label,
            permissions=[PermissionInfo(key=p.key, label=p.label, description=p.description) for p in g.permissions],
            levels=[
                AccessLevel(key=lv.key, label=lv.label, permissions=list(lv.permissions), implies=list(lv.implies))
                for lv in g.levels
            ],
        )
        for g in CATALOG
    ]


# ---------- helpers ----------

def _audit(action: str, actor: CurrentUser, ip: Optional[str], target, detail: Optional[dict] = None) -> None:
    audit.record(
        action, actor_user_id=actor.user_id, actor_username=actor.username, target_type="user",
        target_id=str(target.user_id), detail={"user": target.username, **(detail or {})}, ip=ip,
    )


def _validate_permissions(permissions: list[str]) -> set[str]:
    unknown = sorted(set(permissions) - ALL_PERMISSIONS)
    if unknown:
        raise InvalidInput(f"Unknown permission(s): {', '.join(unknown)}")
    return set(permissions)


def _ensure_can_grant(actor: CurrentUser, granted: set[str]) -> None:
    """Nobody can hand out access they don't have themselves (no privilege escalation)."""
    missing = granted - access.permissions_for_role(actor.role)
    if missing:
        raise RuleViolation(f"You can't give permissions you don't have yourself: {', '.join(sorted(missing))}.")


def _ensure_not_more_powerful(actor: CurrentUser, target) -> None:
    """Editing, resetting or unlocking someone with more access than you would be a back door."""
    if access.permissions_for_role(target.role) - access.permissions_for_role(actor.role):
        raise RuleViolation("You can't change a user who has more access than you do.")


def _make_private_set(user_id: str, label: str, permissions: set[str]) -> str:
    name = private_role_name(user_id)
    role_repository.create_role(
        name, f"Access for {label}"[:100], "One user's checkmarks (managed from the Users screen).", permissions
    )
    return name


# ---------- operations ----------

def create_user(request: CreateUserRequest, actor: CurrentUser, ip: Optional[str] = None) -> ManagedUserResponse:
    email = request.email.strip().lower()
    # People sign in with their email, so it doubles as the username.
    if user_repository.find_user_by_identifier(email) is not None:
        raise UsernameTaken(email)
    security.validate_password_strength(request.password, email)

    user_id = str(uuid.uuid4())
    if request.is_admin:
        if actor.role != ADMIN_ROLE:
            raise RuleViolation("Only an administrator can create another administrator.")
        role_name, permissions = ADMIN_ROLE, set(ALL_PERMISSIONS)
    else:
        permissions = _validate_permissions(request.permissions)
        _ensure_can_grant(actor, permissions)
        role_name = _make_private_set(user_id, email, permissions)

    try:
        user_repository.create_user(
            username=email,
            password_hash=security.hash_password(request.password),
            role=role_name,
            display_name=(request.display_name or "").strip() or None,
            email=email,
            user_id=user_id,
        )
    except Exception:
        if role_name != ADMIN_ROLE:
            role_repository.delete_role(role_name)  # don't leave an orphan set behind
        raise
    access.invalidate()
    created = _get_or_404(user_id)
    _audit("user.create", actor, ip, created,
           {"admin": request.is_admin, "permissions": [] if request.is_admin else sorted(permissions)})
    return _fresh(user_id)


def update_user(
    user_id: str, request: UpdateUserRequest, actor: CurrentUser, ip: Optional[str] = None
) -> ManagedUserResponse:
    target = _get_or_404(user_id)
    is_self = str(target.user_id).lower() == actor.user_id.lower()
    if not is_self:
        _ensure_not_more_powerful(actor, target)

    currently_admin = target.role == ADMIN_ROLE
    new_admin = currently_admin if request.is_admin is None else request.is_admin
    if new_admin != currently_admin and actor.role != ADMIN_ROLE:
        raise RuleViolation("Only an administrator can grant or remove administrator access.")

    losing_admin = currently_admin and bool(target.is_active) and (not new_admin or request.is_active is False)
    if losing_admin:
        if is_self:
            raise RuleViolation("You can't remove your own admin access or deactivate yourself.")
        if user_repository.count_active_admins() <= 1:
            raise RuleViolation("There must be at least one active admin.")

    display_name = request.display_name.strip() if request.display_name is not None else None
    email = request.email.strip().lower() if request.email is not None else None
    if email:
        owner = user_repository.find_user_by_identifier(email)
        if owner is not None and str(owner.user_id).lower() != str(target.user_id).lower():
            raise EmailTaken(email)

    changes: dict = {}
    new_role: Optional[str] = None
    old_private_to_delete: Optional[str] = None
    label = target.email or target.username

    if new_admin and not currently_admin:
        new_role = ADMIN_ROLE
        changes["is_admin"] = True
        if is_private_role(target.role):
            old_private_to_delete = target.role
    elif not new_admin:
        current_perms = set(access.permissions_for_role(target.role))
        if currently_admin:
            # Demotion: the admin's checkmarks have to come from the request.
            if request.permissions is None:
                raise RuleViolation("Choose what this user can access.")
            new_perms = _validate_permissions(request.permissions)
            _ensure_can_grant(actor, new_perms)
            new_role = _make_private_set(str(target.user_id), label, new_perms)
            changes["is_admin"] = False
            changes["permissions"] = sorted(new_perms)
        elif request.permissions is not None:
            new_perms = _validate_permissions(request.permissions)
            _ensure_can_grant(actor, new_perms - current_perms)
            if is_self:
                for locked in LOCKOUT_PERMISSIONS:
                    if locked in current_perms and locked not in new_perms:
                        raise RuleViolation("You can't remove your own ability to manage users.")
            if new_perms != current_perms:
                if is_private_role(target.role):
                    role_repository.update_role(target.role, None, None, new_perms)
                else:  # still on a shared built-in set: give them their own, starting from what they have
                    new_role = _make_private_set(str(target.user_id), label, new_perms)
                changes["added"] = sorted(new_perms - current_perms)
                changes["removed"] = sorted(current_perms - new_perms)

    user_repository.update_user(user_id, display_name, new_role, request.is_active, email)
    leave = _apply_leave(request, target, is_self)
    if leave is not None:
        changes["leave"] = leave
    if old_private_to_delete:
        role_repository.delete_role(old_private_to_delete)  # only after the user no longer points at it

    if request.is_active is not None and request.is_active != bool(target.is_active):
        changes["is_active"] = request.is_active
    if email is not None and email != (target.email or ""):
        changes["email"] = email
    if display_name is not None and display_name != (target.display_name or ""):
        changes["display_name"] = display_name

    # Access edits bite within seconds because every request re-checks it (the cache is dropped here).
    # Deactivation also ends the user's sessions straight away.
    if request.is_active is False:
        user_repository.revoke_all_sessions(user_id)
        if bool(target.is_active):
            case_pipeline.handle_user_left(target.username, target.display_name, str(target.user_id))       # their open requests and approvals are not left unattended
    access.invalidate()
    _audit("user.update", actor, ip, target, changes or None)
    if leave is not None:
        case_pipeline.reroute_pending_approvals()           # waiting approvals go to whoever is asked now (and the admins if nobody)
    return _fresh(user_id)


def reset_password(user_id: str, request: ResetPasswordRequest, actor: CurrentUser, ip: Optional[str] = None) -> None:
    target = _get_or_404(user_id)
    _ensure_not_more_powerful(actor, target)
    security.validate_password_strength(request.new_password, target.username)
    user_repository.set_password(user_id, security.hash_password(request.new_password))
    user_repository.revoke_all_sessions(user_id)
    _audit("user.reset_password", actor, ip, target)


def delete_user(user_id: str, actor: CurrentUser, ip: Optional[str] = None) -> None:
    """Permanently delete a user. For someone who may come back, deactivating is the gentler choice."""
    target = _get_or_404(user_id)
    if str(target.user_id).lower() == actor.user_id.lower():
        raise RuleViolation("You can't delete your own account.")
    _ensure_not_more_powerful(actor, target)
    if target.role == ADMIN_ROLE and bool(target.is_active) and user_repository.count_active_admins() <= 1:
        raise RuleViolation("There must be at least one active admin.")

    user_repository.revoke_all_sessions(user_id)
    user_repository.delete_user(user_id)
    if is_private_role(target.role):
        role_repository.delete_role(target.role)  # their own checkmark set goes with them
    access.invalidate()
    case_pipeline.handle_user_left(target.username, target.display_name, str(target.user_id))
    _audit("user.delete", actor, ip, target, {"email": target.email, "role": target.role})


def open_session(user_id: str, actor: CurrentUser, ip: Optional[str] = None) -> OpenedAccount:
    """An administrator opens another account (a department's) without its password: a one-hour sign-in for that
    account only. Never for another administrator, never for a switched-off account, and always in the audit log."""
    from app.controllers.auth_controller import _to_user_response  # local: auth_controller also uses this module's neighbours

    if not settings.ALLOW_OPEN_ACCOUNT:
        raise RuleViolation("Opening another account is switched off.")
    if actor.role != ADMIN_ROLE or actor.impersonated_by:
        raise RuleViolation("Only an administrator, signed in as themselves, can open another account.")
    target = _get_or_404(user_id)
    if target.role == ADMIN_ROLE:
        raise RuleViolation("An administrator's account can't be opened this way.")
    if not target.is_active:
        raise RuleViolation("That account is switched off. Switch it on first.")

    token, expires_in = security.create_access_token(
        str(target.user_id), target.username, target.role, minutes=settings.OPEN_ACCOUNT_MINUTES, impersonator=actor.username)
    _audit("user.open_account", actor, ip, target, {"as": target.username, "minutes": settings.OPEN_ACCOUNT_MINUTES})
    return OpenedAccount(access_token=token, expires_in=expires_in, user=_to_user_response(target), opened_by=actor.username)


def unlock_user(user_id: str, actor: CurrentUser, ip: Optional[str] = None) -> ManagedUserResponse:
    target = _get_or_404(user_id)
    _ensure_not_more_powerful(actor, target)
    user_repository.unlock_user(user_id)
    _audit("user.unlock", actor, ip, target)
    return _fresh(user_id)
