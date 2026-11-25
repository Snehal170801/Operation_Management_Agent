"""Links that let a manager decide an approval straight from the email. See core/email_approval.py for the rules."""

import secrets
import uuid
from datetime import datetime, timezone

from app.core import email_approval, security
from app.core.config import settings
from app.repositories import approval_link_repository


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_link(approval_id: str, user_id: str) -> str:
    """A new link for this person and approval (their earlier link, if any, stops working). Returns the secret to put in the email;
    only its hash is kept."""
    token = secrets.token_urlsafe(32)
    approval_link_repository.revoke_for(approval_id, user_id)
    approval_link_repository.insert_link(
        str(uuid.uuid4()), approval_id, user_id, security.hash_refresh_token(token), email_approval.expires_at(_now(), settings.EMAIL_APPROVE_HOURS))
    return token


def find(token: str) -> dict | None:
    row = approval_link_repository.find_by_hash(security.hash_refresh_token(token)) if token and len(token) <= 200 else None
    if row is None:
        return None
    return {"link_id": str(row.link_id), "approval_id": str(row.approval_id), "user_id": str(row.user_id), "created_at": row.created_at,
            "expires_at": row.expires_at, "used_at": row.used_at, "used_action": row.used_action, "revoked_at": row.revoked_at}


def use(link_id: str, action: str, ip: str | None) -> bool:
    return approval_link_repository.mark_used(link_id, action, ip)


def revoke_user_links(user_id: str) -> int:
    """This person can no longer decide: their unused links stop working now (the page also refuses them on its own, this closes the door early)."""
    return approval_link_repository.revoke_for_user(user_id)


def revoke_all(approval_id: str) -> None:
    """The approval was decided (in the app, say): every outstanding link for it stops working."""
    approval_link_repository.revoke_for(approval_id)
