from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

_EMAIL = r"[^@\s]+@[^@\s]+\.[^@\s]+"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)  # the user's email
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False


class UserResponse(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    role: str
    permissions: list[str] = []


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class OpenedAccount(AuthResponse):
    """A short-lived sign-in for another account, opened by an administrator."""

    opened_by: str


class CurrentUser(BaseModel):
    user_id: str
    username: str
    role: str
    # Set when an administrator opened this account from the Accounts tab (the admin's username)
    impersonated_by: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=150)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


# ---------- user management (admin) ----------

class ManagedUserResponse(BaseModel):
    user_id: str
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    is_admin: bool
    permissions: list[str]  # what they can do (an admin holds everything)
    is_active: bool
    is_locked: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    on_leave_from: Optional[date] = None
    on_leave_until: Optional[date] = None
    on_leave_now: bool = False
    delegate_user_id: Optional[str] = None
    delegate_name: Optional[str] = None


class CreateUserRequest(BaseModel):
    email: str = Field(pattern=f"^{_EMAIL}$", max_length=254)
    display_name: Optional[str] = Field(default=None, max_length=150)
    password: str = Field(min_length=1, max_length=128)
    # Full access incl. managing users. Ignored `permissions` when true. Only an admin can grant it.
    is_admin: bool = False
    permissions: list[str] = []


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=150)
    email: Optional[str] = Field(default=None, pattern=f"^({_EMAIL})?$", max_length=254)
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    # The user's complete set of permissions (omit to leave it unchanged).
    permissions: Optional[list[str]] = None
    # Leave and the backup approver. Only fields that are SENT change (null clears): see user_controller.update_user.
    on_leave_from: Optional[date] = None
    on_leave_until: Optional[date] = None
    delegate_user_id: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


# ---------- permission catalog (drives the access checkmarks) ----------

class PermissionInfo(BaseModel):
    key: str
    label: str
    description: str


class AccessLevel(BaseModel):
    """One checkbox: ticking it grants `permissions`; `implies` lists levels that must also be ticked."""

    key: str
    label: str
    permissions: list[str]
    implies: list[str] = []


class DepartmentInfo(BaseModel):
    """A department: the people asked when its agent is stuck. A quick way to tick the right permissions."""

    key: str
    label: str
    agent: str
    handles: str
    permissions: list[str]


class PermissionGroup(BaseModel):
    resource: str
    label: str
    permissions: list[PermissionInfo]
    levels: list[AccessLevel]


# ---------- audit log ----------

class AuditEntryResponse(BaseModel):
    audit_id: int
    actor_user_id: Optional[str] = None
    actor_username: Optional[str] = None
    action: str
    outcome: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime


class AuditPageResponse(BaseModel):
    total: int
    items: list[AuditEntryResponse]


# ---------- forgot password (one-time code) ----------

class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)


class ResetWithOtpRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)
    otp: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=1, max_length=128)


class MessageResponse(BaseModel):
    message: str
