from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.models.auth_schemas import CurrentUser

from app.controllers import delivery_controller
from app.agents import delivery_agent
from app.controllers import receipt_controller
from app.models.delivery_schemas import ConfirmDeliveryRequest, DeliveryResponse, DisputeHandledRequest, ReceiptResponse, ShortCloseRequest

router = APIRouter(prefix="/cases/{case_id}/delivery", tags=["delivery"])


@router.get("", response_model=DeliveryResponse | None)
def get_delivery(case_id: str):
    return delivery_controller.get_delivery(case_id)


@router.post("/received", response_model=DeliveryResponse)
def confirm_delivery(case_id: str, request: ConfirmDeliveryRequest, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """A person confirms the goods arrived. This stops the automatic vendor chasing."""
    return delivery_controller.confirm_delivery(case_id, request, user)


@router.post("/dispute-handled", status_code=204)
def dispute_handled(case_id: str, request: DisputeHandledRequest, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """Receiving records that they followed up after the requester said the goods had not reached them."""
    receipt_controller.dispute_handled(case_id, request.note, user)


@router.get("/receipt", response_model=ReceiptResponse)
def get_receipt(case_id: str):
    """What the requester said about receiving the goods (for the staff who follow up)."""
    return delivery_agent.get_receipt(case_id)


@router.post("/short-close", response_model=DeliveryResponse)
def short_close(case_id: str, request: ShortCloseRequest, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """The supplier will not send the rest: accept the order as delivered with what has arrived."""
    return delivery_controller.short_close(case_id, request.note, user)
