from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import case_change_controller
from app.models.auth_schemas import CurrentUser
from app.models.case_change_schemas import (
    CancelRequest, ChangeOptions, ChangeOutcome, ChangeRequest, ResolveCancelRequest, ResolveChangeRequest,
)

# The requester (own request) or staff who can edit cases may cancel or change; the controller checks which.
router = APIRouter(prefix="/cases/{case_id}", tags=["case-changes"])

_signed_in = require_permission("cases:read")


@router.get("/change-options", response_model=ChangeOptions)
def options(case_id: str, user: CurrentUser = Depends(_signed_in)):
    return case_change_controller.get_options(case_id, user)


@router.post("/cancel", response_model=ChangeOutcome)
def cancel(case_id: str, request: CancelRequest, user: CurrentUser = Depends(_signed_in)):
    """Cancel the request. Before an order goes out it ends at once; after, the supplier is asked to cancel."""
    return case_change_controller.cancel(case_id, request.reason, user)


@router.post("/change", response_model=ChangeOutcome)
def change(case_id: str, request: ChangeRequest, user: CurrentUser = Depends(_signed_in)):
    """Change quantities. Before an order goes out suppliers are asked again; after, the PO desk agrees it with the supplier."""
    return case_change_controller.change(case_id, request.quantities, request.note, user)


@router.post("/cancel/resolve", response_model=ChangeOutcome)
def resolve_cancel(case_id: str, request: ResolveCancelRequest, user: CurrentUser = Depends(require_permission("po:manage"))):
    """PO desk: settle a cancellation the supplier refused or never answered, or carry on with the order."""
    return case_change_controller.resolve_cancel(case_id, request.action, request.note, user)


@router.post("/change/resolve", response_model=ChangeOutcome)
def resolve_change(case_id: str, request: ResolveChangeRequest, user: CurrentUser = Depends(require_permission("po:manage"))):
    """PO desk: record what the supplier agreed to for a change to an order they already had."""
    return case_change_controller.resolve_change(case_id, request.action, request.total_amount, request.note, user)
