from fastapi import APIRouter, Depends, Request

from app.api.deps import client_ip, require_permission
from app.controllers import user_controller
from app.models.auth_schemas import (
    CreateUserRequest,
    CurrentUser,
    DepartmentInfo,
    ManagedUserResponse,
    OpenedAccount,
    PermissionGroup,
    ResetPasswordRequest,
    UpdateUserRequest,
)

router = APIRouter(prefix="/users", tags=["users"])

reader = Depends(require_permission("users:read"))
writer = Depends(require_permission("users:write"))


@router.get("", response_model=list[ManagedUserResponse])
def list_users(_: CurrentUser = reader):
    return user_controller.list_users()


@router.get("/permissions", response_model=list[PermissionGroup])
def permission_catalog(_: CurrentUser = reader):
    """The modules and their checkmarks (Read only / CRUD ...) shown on the add/edit-user forms."""
    return user_controller.catalog()


@router.get("/departments", response_model=list[DepartmentInfo])
def departments(_: CurrentUser = reader):
    """The departments (one per agent) with the permissions each one needs, for the add/edit-user forms."""
    return user_controller.departments()


@router.post("/{user_id}/open-session", response_model=OpenedAccount)
def open_session(user_id: str, request: Request, actor: CurrentUser = writer):
    """Administrators only: a one-hour sign-in for another account, for the Accounts tab. Recorded in the audit log."""
    return user_controller.open_session(user_id, actor, client_ip(request))


@router.post("", response_model=ManagedUserResponse, status_code=201)
def create_user(body: CreateUserRequest, request: Request, actor: CurrentUser = writer):
    return user_controller.create_user(body, actor, client_ip(request))


@router.patch("/{user_id}", response_model=ManagedUserResponse)
def update_user(user_id: str, body: UpdateUserRequest, request: Request, actor: CurrentUser = writer):
    return user_controller.update_user(user_id, body, actor, client_ip(request))


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, request: Request, actor: CurrentUser = writer):
    user_controller.delete_user(user_id, actor, client_ip(request))


@router.post("/{user_id}/reset-password", status_code=204)
def reset_password(user_id: str, body: ResetPasswordRequest, request: Request, actor: CurrentUser = writer):
    user_controller.reset_password(user_id, body, actor, client_ip(request))


@router.post("/{user_id}/unlock", response_model=ManagedUserResponse)
def unlock_user(user_id: str, request: Request, actor: CurrentUser = writer):
    return user_controller.unlock_user(user_id, actor, client_ip(request))
