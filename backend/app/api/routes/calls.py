from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.agents import calling_agent
from app.api.deps import client_ip, require_permission
from app.core import audit
from app.models.auth_schemas import CurrentUser

router = APIRouter(prefix="/calls", tags=["calls"])


class StartCallRequest(BaseModel):
    to: str = Field(max_length=20, description="E.164 number, e.g. +919325642310")
    case_id: Optional[str] = Field(default=None, max_length=50)


@router.get("/status")
def calling_status(_: CurrentUser = Depends(require_permission("vendors:read"))):
    from app.core.config import settings

    # allowed_numbers: who the server will ring. Empty means any number is allowed.
    return {"configured": calling_agent.is_configured(), "allowed_numbers": list(settings.CALL_ALLOWED_NUMBERS)}


@router.post("", status_code=202)
def start_call(body: StartCallRequest, request: Request, user: CurrentUser = Depends(require_permission("vendors:write"))):
    result = calling_agent.start_call(body.to.strip(), body.case_id)
    audit.record("call.start", actor_user_id=user.user_id, actor_username=user.username, target_type="call",
                 target_id=result["call_sid"], detail={"to": body.to, "case_id": body.case_id}, ip=client_ip(request))
    return result


@router.post("/{call_sid}/end", status_code=204)
def end_call(call_sid: str, request: Request, user: CurrentUser = Depends(require_permission("vendors:write"))):
    calling_agent.end_call(call_sid)
    audit.record("call.end", actor_user_id=user.user_id, actor_username=user.username, target_type="call",
                 target_id=call_sid, ip=client_ip(request))
