from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.api.deps import require_permission
from app.core import presence
from app.models.auth_schemas import CurrentUser

router = APIRouter(prefix="/presence", tags=["presence"])


class Others(BaseModel):
    others: list[str]


@router.post("/cases/{case_id}", response_model=Others)
def look(case_id: str, user: CurrentUser = Depends(require_permission("cases:read_all"))):
    """"I have this case open." Staff only. Returns who else has it open right now."""
    return Others(others=presence.checkin(case_id, user.username))


@router.delete("/cases/{case_id}", status_code=204)
def leave(case_id: str, user: CurrentUser = Depends(require_permission("cases:read_all"))):
    presence.leave(case_id, user.username)
    return Response(status_code=204)
