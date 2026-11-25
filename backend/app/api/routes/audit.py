from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permission
from app.controllers import audit_controller
from app.models.auth_schemas import AuditPageResponse

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_permission("audit:read"))])


@router.get("", response_model=AuditPageResponse)
def list_audit(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, max_length=100, description="action prefix, e.g. 'auth.' or 'role.'"),
    outcome: Optional[str] = Query(None, pattern="^(success|failure|denied)$"),
    search: Optional[str] = Query(None, max_length=100),
    days: Optional[int] = Query(None, ge=1, le=365),
):
    return audit_controller.list_entries(limit, offset, action, outcome, search, days)
