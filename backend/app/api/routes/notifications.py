from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import notification_controller
from app.models.auth_schemas import CurrentUser
from app.models.notification_schemas import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
def list_notifications(user: CurrentUser = Depends(require_permission("cases:read"))):
    """The bell: what needs the signed-in person's attention (staff), or progress on their own
    requests (requesters). Always scoped to the caller; there is no way to ask about someone else."""
    return notification_controller.list_notifications(user)
