import json
from datetime import timedelta
from typing import Optional

from app.core import security
from app.models.auth_schemas import AuditEntryResponse, AuditPageResponse
from app.repositories import audit_repository


def _detail(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"value": value}
    except ValueError:
        return {"raw": raw}


def list_entries(
    limit: int, offset: int, action: Optional[str], outcome: Optional[str], search: Optional[str], days: Optional[int]
) -> AuditPageResponse:
    since = security.utcnow() - timedelta(days=days) if days else None
    total, rows = audit_repository.find_entries(limit, offset, action, outcome, search, since)
    return AuditPageResponse(
        total=total,
        items=[
            AuditEntryResponse(
                audit_id=r.audit_id,
                actor_user_id=str(r.actor_user_id) if r.actor_user_id else None,
                actor_username=r.actor_username,
                action=r.action,
                outcome=r.outcome,
                target_type=r.target_type,
                target_id=r.target_id,
                detail=_detail(r.detail),
                ip_address=r.ip_address,
                created_at=r.created_at,
            )
            for r in rows
        ],
    )
