from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.controllers import approval_controller
from app.models.approval_schemas import ApprovalResponse, ApprovalReview, DecideApprovalRequest
from app.models.auth_schemas import CurrentUser

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalResponse])
def get_approvals(status: Optional[str] = None, case_id: Optional[str] = None):
    """Use ?status=pending for the human 'needs attention' queue."""
    return approval_controller.get_approvals(status, case_id)


@router.get("/{approval_id}/review", response_model=ApprovalReview)
def get_review(approval_id: str):
    """Everything needed to decide: the request, every supplier's reply, the AI's ranking and its reasons."""
    return approval_controller.get_review(approval_id)


@router.get("/{approval_id}", response_model=ApprovalResponse)
def get_approval(approval_id: str):
    return approval_controller.get_approval(approval_id)


# Both decisions are POSTs, so the router-level guard already requires approvals:write.
@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
def approve(approval_id: str, request: DecideApprovalRequest, user: CurrentUser = Depends(get_current_user)):
    return approval_controller.approve(approval_id, request, user)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
def reject(approval_id: str, request: DecideApprovalRequest, user: CurrentUser = Depends(get_current_user)):
    return approval_controller.reject(approval_id, request, user)
