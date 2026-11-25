import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import InvalidToken

# bcrypt only reads the first 72 bytes; refuse longer input instead of silently truncating.
MAX_PASSWORD_BYTES = 72


MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str, username: str = "") -> None:
    """Raises WeakPassword with a user-facing reason."""
    from app.core.exceptions import WeakPassword

    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise WeakPassword(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    if not (any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password)):
        raise WeakPassword("Password must include an uppercase letter, a lowercase letter and a number.")
    handle = username.split("@")[0] if username else ""
    if len(handle) >= 3 and handle.lower() in password.lower():
        raise WeakPassword("Password must not contain your username or email name.")


def utcnow() -> datetime:
    """Naive UTC, matching the DATETIME2 / SYSUTCDATETIME() columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except ValueError:
        return False


# Verified against when the username doesn't exist, so "unknown user" and
# "wrong password" cost the same time and can't be told apart by timing.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def create_access_token(user_id: str, username: str, role: str, minutes: int | None = None,
                        impersonator: str | None = None) -> tuple[str, int]:
    """Returns (token, lifetime in seconds). `impersonator` marks a token an administrator opened for someone else."""
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=minutes or settings.ACCESS_TOKEN_MINUTES)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + lifetime,
        **({"imp": impersonator} if impersonator else {}),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise InvalidToken("Session expired")
    except jwt.PyJWTError:
        raise InvalidToken()
    if payload.get("type") != "access":
        raise InvalidToken()
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_otp() -> str:
    """6 digits from the OS CSPRNG (zero-padded)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(user_id: str, otp: str) -> str:
    """Keyed hash bound to the user, so a leaked table can't be brute-forced without the secret."""
    return hmac.new(
        settings.JWT_SECRET.encode("utf-8"), f"{user_id.lower()}:{otp}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
