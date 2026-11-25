from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import dashboard_controller
from app.models.auth_schemas import CurrentUser
from app.models.dashboard_schemas import DashboardSnapshot

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSnapshot)
def get_dashboard(user: CurrentUser = Depends(require_permission("dashboard:read"))):
    """A small summary of everything, cheap enough for the screen to ask for every few seconds."""
    return dashboard_controller.get_snapshot(user)
