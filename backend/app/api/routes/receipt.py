from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import receipt_controller
from app.models.auth_schemas import CurrentUser
from app.models.delivery_schemas import ReceiptRequest, ReceiptResponse

# The requester's own check that the goods arrived. Only the person who asked can use it, on their own case.
router = APIRouter(prefix="/cases/{case_id}/receipt", tags=["delivery"])


@router.get("", response_model=ReceiptResponse)
def get_receipt(case_id: str, user: CurrentUser = Depends(require_permission("cases:read"))):
    return receipt_controller.get_receipt(case_id, user)


@router.post("", response_model=ReceiptResponse)
def answer(case_id: str, request: ReceiptRequest, user: CurrentUser = Depends(require_permission("cases:read"))):
    """"Yes, I got it" or "No, not received". A "no" alerts the Receiving team."""
    return receipt_controller.answer(case_id, request.received, request.note, user)
