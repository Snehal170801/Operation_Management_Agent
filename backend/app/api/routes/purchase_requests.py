from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import purchase_controller
from app.models.auth_schemas import CurrentUser
from app.models.purchase_schemas import PurchaseRequestResponse

router = APIRouter(prefix="/purchase-requests", tags=["purchase-requests"])


@router.get("/{case_id}", response_model=PurchaseRequestResponse)
def get_purchase_request(case_id: str, user: CurrentUser = Depends(require_permission("cases:read"))):
    return purchase_controller.get_purchase_request(case_id, user)
