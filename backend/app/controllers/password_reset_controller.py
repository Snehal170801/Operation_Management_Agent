import hmac
import logging
from datetime import timedelta
from typing import Optional

from fastapi import BackgroundTasks

from app.clients import email_client
from app.core import audit, security
from app.core.config import settings
from app.core.exceptions import InvalidOtp
from app.models.auth_schemas import ForgotPasswordRequest, ResetWithOtpRequest
from app.repositories import user_repository

logger = logging.getLogger("app.auth.reset")

# Always returned, whether or not the account exists, so this endpoint can't be used
# to discover which emails have accounts.
GENERIC_REQUEST_MESSAGE = (
    "If an account exists for that email, we've sent a 6-digit code. It expires in {minutes} minutes."
)


def _send_code_email(email: str, otp: str) -> None:
    if not settings.SMTP_HOST and settings.ENVIRONMENT == "production":
        # Never log a live code in production just because mail isn't configured yet.
        logger.error("password reset requested but SMTP is not configured; no email sent")
        return
    try:
        email_client.send_email(
            to=email,
            subject="Your Operation Agents password reset code",
            body=(
                f"Your password reset code is: {otp}\n\n"
                f"It expires in {settings.OTP_TTL_MINUTES} minutes and can be used once.\n"
                "If you didn't ask to reset your password, you can ignore this email; "
                "your password has not been changed.\n"
            ),
        )
    except Exception:
        logger.exception("failed to send password reset email")


def _send_changed_notice(email: str) -> None:
    try:
        email_client.send_email(
            to=email,
            subject="Your Operation Agents password was changed",
            body=(
                "Your password was just reset using an emailed code and you were signed out everywhere.\n"
                "If this wasn't you, contact your administrator immediately.\n"
            ),
        )
    except Exception:
        logger.exception("failed to send password-changed notice")


def request_reset(request: ForgotPasswordRequest, ip: Optional[str], background: BackgroundTasks) -> str:
    message = GENERIC_REQUEST_MESSAGE.format(minutes=settings.OTP_TTL_MINUTES)
    row = user_repository.find_user_by_identifier(request.identifier.strip())

    if row is None or not row.is_active or not row.email:
        logger.info("reset requested for unknown/inactive/email-less account from %s", ip)
        return message

    user_id = str(row.user_id)
    now = security.utcnow()

    last = user_repository.find_latest_otp(user_id)
    if last is not None and (now - last.created_at).total_seconds() < settings.OTP_RESEND_SECONDS:
        return message  # cooldown: silently keep the code already sent
    if user_repository.count_otps_since(user_id, now - timedelta(hours=1)) >= settings.OTP_MAX_PER_HOUR:
        logger.warning("reset code limit reached for %r", row.username)
        return message

    otp = security.generate_otp()
    user_repository.invalidate_otps(user_id)  # only the newest code works
    user_repository.insert_otp(
        user_id, security.hash_otp(user_id, otp), now + timedelta(minutes=settings.OTP_TTL_MINUTES), ip
    )
    audit.record("auth.password_reset_requested", actor_user_id=user_id, actor_username=row.username, ip=ip)
    # Sent after the response so timing doesn't reveal whether the account exists.
    background.add_task(_send_code_email, row.email, otp)
    return message


def confirm_reset(request: ResetWithOtpRequest, ip: Optional[str], background: BackgroundTasks) -> None:
    row = user_repository.find_user_by_identifier(request.identifier.strip())
    if row is None or not row.is_active:
        raise InvalidOtp()

    user_id = str(row.user_id)
    latest = user_repository.find_latest_otp(user_id)
    now = security.utcnow()
    if (
        latest is None
        or latest.used_at is not None
        or latest.expires_at <= now
        or latest.attempts >= settings.OTP_MAX_ATTEMPTS
    ):
        raise InvalidOtp()

    if not hmac.compare_digest(latest.otp_hash, security.hash_otp(user_id, request.otp)):
        user_repository.increment_otp_attempts(str(latest.otp_id))
        audit.record("auth.password_reset", actor_user_id=user_id, actor_username=row.username,
                     outcome="failure", detail={"reason": "wrong_code"}, ip=ip)
        if latest.attempts + 1 >= settings.OTP_MAX_ATTEMPTS:
            user_repository.invalidate_otps(user_id)
            logger.warning("reset code burned after too many wrong tries for %r from %s", row.username, ip)
        raise InvalidOtp()

    # Checked after the code but before consuming it, so a too-weak password doesn't waste the code.
    security.validate_password_strength(request.new_password, row.username)

    user_repository.set_password(user_id, security.hash_password(request.new_password))
    user_repository.invalidate_otps(user_id)
    user_repository.revoke_all_sessions(user_id)
    logger.info("password reset by code: %r from %s", row.username, ip)
    audit.record("auth.password_reset", actor_user_id=user_id, actor_username=row.username, ip=ip)
    if row.email:
        background.add_task(_send_changed_notice, row.email)
