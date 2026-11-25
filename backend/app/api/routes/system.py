from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import system_controller
from app.api.deps import get_current_user
from app.models.auth_schemas import CurrentUser
from app.models.system_schemas import AutomationResponse, SetAutomationRequest, SystemHealthResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get(
    "/health",
    response_model=SystemHealthResponse,
    dependencies=[Depends(require_permission("system:read"))],
)
def system_health():
    return system_controller.get_health()


@router.get(
    "/automation",
    response_model=AutomationResponse,
    dependencies=[Depends(require_permission("system:read"))],
)
def get_automation():
    return system_controller.get_automation()


@router.post("/automation", response_model=AutomationResponse)
def set_automation(
    request: SetAutomationRequest,
    user: CurrentUser = Depends(require_permission("system:write")),
):
    """The pause switch: stops (or restarts) everything the agents do on their own."""
    return system_controller.set_automation(request.paused, user)
