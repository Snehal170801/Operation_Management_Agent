from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import agent_flow_controller
from app.models.agent_flow_schemas import AgentBoard, AgentInfo, AgentReplay, AgentFlowCase, AgentFlowState
from app.models.auth_schemas import CurrentUser

# Open to requesters as well as staff: the controller limits a requester to their own cases and words
# everything for the audience (see app/core/agent_flow.py).
router = APIRouter(prefix="/agent-flow", tags=["agent-flow"])

_guard = require_permission("cases:read")


@router.get("/cases", response_model=list[AgentFlowCase])
def list_cases(user: CurrentUser = Depends(_guard)):
    return agent_flow_controller.list_cases(user)


@router.get("/cases/{case_id}", response_model=AgentFlowState)
def get_flow(case_id: str, user: CurrentUser = Depends(_guard)):
    return agent_flow_controller.get_flow(case_id, user)


@router.get("/cases/{case_id}/agents/{agent_key}", response_model=AgentInfo)
def get_agent_info(case_id: str, agent_key: str, at: Optional[datetime] = None, user: CurrentUser = Depends(_guard)):
    """Everything one agent did on this case (what you see when you click it). With `at`, as it was at that moment (replay)."""
    if at is not None and at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)  # the database keeps naive UTC
    return agent_flow_controller.get_agent_info(case_id, agent_key, user, at)


@router.get("/cases/{case_id}/replay", response_model=AgentReplay)
def get_replay(case_id: str, user: CurrentUser = Depends(_guard)):
    return agent_flow_controller.get_replay(case_id, user)


@router.get("/board", response_model=AgentBoard)
def get_board(_: CurrentUser = Depends(require_permission("cases:read_all"))):
    """Staff only: how many cases each agent is working on, waiting on or blocked on right now."""
    return agent_flow_controller.get_board()
