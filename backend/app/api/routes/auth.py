from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user
from app.controllers import auth_controller, password_reset_controller
from app.core.config import settings
from app.core.exceptions import InvalidToken
from app.models.auth_schemas import (
    AuthResponse,
    ChangePasswordRequest,
    CurrentUser,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetWithOtpRequest,
    UpdateProfileRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
# Scoped to /auth so the browser only sends it to the refresh/logout endpoints.
REFRESH_COOKIE_PATH = "/auth"


def _client(request: Request) -> tuple[Optional[str], Optional[str]]:
    return request.headers.get("user-agent"), request.client.host if request.client else None


def _set_refresh_cookie(response: Response, session: auth_controller.Session) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=session.refresh_token,
        max_age=session.cookie_max_age,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )
    # Tokens must never be cached by the browser or a proxy.
    response.headers["Cache-Control"] = "no-store"


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, request: Request, response: Response):
    user_agent, ip = _client(request)
    session = auth_controller.login(body, user_agent, ip)
    _set_refresh_cookie(response, session)
    return session.auth


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=REFRESH_COOKIE),
):
    user_agent, ip = _client(request)
    try:
        session = auth_controller.refresh(refresh_token, user_agent, ip)
    except InvalidToken as exc:
        # A dead cookie is useless; clear it so the client stops sending it. This has to be
        # an explicit response: headers set on `response` are dropped when an exception is raised.
        failure = JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
        failure.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
        return failure
    _set_refresh_cookie(response, session)
    return session.auth


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=REFRESH_COOKIE),
):
    auth_controller.logout(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=UserResponse)
def me(current: CurrentUser = Depends(get_current_user)):
    return auth_controller.get_me(current)


@router.patch("/me", response_model=UserResponse)
def update_me(body: UpdateProfileRequest, current: CurrentUser = Depends(get_current_user)):
    return auth_controller.update_profile(current, body)


@router.post("/change-password", response_model=AuthResponse)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    current: CurrentUser = Depends(get_current_user),
):
    """Ends every session (other devices included) and starts a fresh one on this device."""
    user_agent, ip = _client(request)
    session = auth_controller.change_password(current, body, user_agent, ip)
    _set_refresh_cookie(response, session)
    return session.auth


# ---------- forgot password (emailed one-time code) ----------

@router.post("/forgot-password", response_model=MessageResponse, status_code=202)
def forgot_password(body: ForgotPasswordRequest, request: Request, background: BackgroundTasks):
    """Always answers the same way, whether or not the account exists."""
    _, ip = _client(request)
    return MessageResponse(message=password_reset_controller.request_reset(body, ip, background))


@router.post("/forgot-password/confirm", response_model=MessageResponse)
def confirm_forgot_password(body: ResetWithOtpRequest, request: Request, background: BackgroundTasks):
    """Verifies the code and sets the new password. Ends every session for that user."""
    _, ip = _client(request)
    password_reset_controller.confirm_reset(body, ip, background)
    return MessageResponse(message="Password updated. You can now sign in.")
