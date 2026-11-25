from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.models.auth_schemas import CurrentUser

from app.controllers import purchase_order_controller
from app.models.purchase_order_schemas import ConfirmPurchaseOrderRequest, PurchaseOrderResponse

router = APIRouter(prefix="/cases/{case_id}/purchase-order", tags=["purchase-orders"])


@router.get("", response_model=PurchaseOrderResponse | None)
def get_purchase_order(case_id: str):
    return purchase_order_controller.get_purchase_order(case_id)


@router.post("", response_model=PurchaseOrderResponse)
def issue_purchase_order(case_id: str, _: CurrentUser = Depends(require_permission("po:manage"))):
    """Retry issuing the PO (e.g. after fixing the vendor's email). Returns the existing PO if one exists."""
    return purchase_order_controller.issue_purchase_order(case_id)


@router.post("/confirmed", response_model=PurchaseOrderResponse)
def confirm_purchase_order(case_id: str, request: ConfirmPurchaseOrderRequest, user: CurrentUser = Depends(require_permission("po:manage"))):
    """Record that the supplier confirmed the order another way (say, by phone), or that a problem they raised is sorted out."""
    return purchase_order_controller.confirm_purchase_order(case_id, request.note, user)
