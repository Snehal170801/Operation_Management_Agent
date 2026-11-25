"""Audit trail: who did what, from where, with what result.

`record()` never raises: failing to write an audit row must not break the action being
audited (it is logged loudly instead).
"""

import json
import logging
from typing import Any, Optional

from app.repositories import audit_repository

logger = logging.getLogger("app.audit")

# Values that must never be written to the audit log, whatever a caller passes in.
_REDACT = {"password", "new_password", "current_password", "otp", "token", "access_token", "refresh_token"}


def _clean(detail: Optional[dict[str, Any]]) -> Optional[str]:
    if not detail:
        return None
    safe = {k: ("***" if k.lower() in _REDACT else v) for k, v in detail.items()}
    return json.dumps(safe, default=str)[:4000]


def record(
    action: str,
    *,
    actor_user_id: Optional[str] = None,
    actor_username: Optional[str] = None,
    outcome: str = "success",
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    ip: Optional[str] = None,
) -> None:
    try:
        audit_repository.insert_entry(
            actor_user_id, actor_username, action, outcome, target_type, target_id, _clean(detail), ip
        )
    except Exception:
        logger.exception("could not write audit entry %s", action)
