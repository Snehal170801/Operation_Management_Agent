from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import config_controller
from app.models.auth_schemas import CurrentUser
from app.models.config_schemas import ConfigResponse, ResetConfigRequest, SaveConfigRequest

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse, dependencies=[Depends(require_permission("system:read"))])
def get_config():
    return config_controller.get_config()


@router.put("", response_model=ConfigResponse)
def save_config(request: SaveConfigRequest, user: CurrentUser = Depends(require_permission("system:write"))):
    """Change one or more settings. All are checked first; if one is wrong nothing is changed."""
    return config_controller.save_config(request.values, user)


@router.post("/reset", response_model=ConfigResponse)
def reset_config(request: ResetConfigRequest, user: CurrentUser = Depends(require_permission("system:write"))):
    """Put the given settings (or all of them) back to their defaults."""
    return config_controller.reset_config(request.keys, user)
