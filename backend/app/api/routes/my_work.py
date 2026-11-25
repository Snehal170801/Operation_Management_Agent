from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import my_work_controller
from app.models.auth_schemas import CurrentUser
from app.models.my_work_schemas import MyWork

router = APIRouter(prefix="/my-work", tags=["my-work"])


@router.get("", response_model=MyWork)
def my_work(user: CurrentUser = Depends(require_permission("cases:read_all"))):
    """The signed-in person's own queue: only the kinds of work their department is allowed to do."""
    return my_work_controller.get_my_work(user)
