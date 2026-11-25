import logging

from app.agents import approval_agent, approval_link_agent
from app.agents import operations_agent, purchase_agent, purchase_order_agent, vendor_agent
from app.core.price_review import build_price_review
from app.core.approval_review import build_review
from app.core.exceptions import ApprovalAlreadyDecided, PurchaseRequestNotFound, VendorSelectionNotFound
from app.core import audit
from app.core.config import settings
from app.core.permissions import ADMIN_ROLE
from app.core.separation import check_not_own_request
from app.models.approval_schemas import ApprovalResponse, ApprovalReview, DecideApprovalRequest
from app.models.auth_schemas import CurrentUser
from app.orchestrator import case_pipeline


def get_approvals(status: str | None, case_id: str | None) -> list[ApprovalResponse]:
    return [ApprovalResponse(**a) for a in approval_agent.get_approvals(status, case_id)]


def get_approval(approval_id: str) -> ApprovalResponse:
    return ApprovalResponse(**approval_agent.get_approval(approval_id))


def get_review(approval_id: str) -> ApprovalReview:
    """The whole picture for one decision: the request, every supplier's reply, the AI's ranking and reasons."""
    return ApprovalReview(**case_pipeline.approval_review(approval_id))


def approve(approval_id: str, request: DecideApprovalRequest, user: CurrentUser) -> ApprovalResponse:
    return _decide(approval_id, True, request, user)


def reject(approval_id: str, request: DecideApprovalRequest, user: CurrentUser) -> ApprovalResponse:
    return _decide(approval_id, False, request, user)


def _decide(approval_id: str, approve: bool, request: DecideApprovalRequest, user: CurrentUser) -> ApprovalResponse:
    # Nobody approves a purchase they asked for themselves (an admin may, on the record).
    case_id = approval_agent.get_approval(approval_id)["case_id"]
    requester = operations_agent.get_case_status(case_id)["requester_id"]
    override = check_not_own_request(user.username, requester, user.role == ADMIN_ROLE)

    # Approving can also pick the supplier. Only a decision still waiting may change anything, so check that first.
    chosen = None
    if approve and request.vendor_id:
        if approval_agent.get_approval(approval_id)["status"] != "pending":
            raise ApprovalAlreadyDecided(approval_id)
        chosen = vendor_agent.choose_vendor(case_id, request.vendor_id, user.username, request.note)

    # Only a rejection that asks for new quotes carries extra options.
    again = {"re_source": True, "skip_selected": request.skip_selected} if request.re_source and not approve else {}
    result = case_pipeline.decide_approval(approval_id, approve, user.username, request.note, **again)
    try:
        approval_link_agent.revoke_all(approval_id)       # the email buttons for this decision no longer work
    except Exception:
        logging.getLogger(__name__).exception("Could not end the email links for approval %s", approval_id)
    audit.record(
        "approval.approve" if approve else "approval.reject",
        actor_user_id=user.user_id, actor_username=user.username,
        target_type="approval", target_id=approval_id,
        detail={"case_id": result["case_id"], "note": request.note, **({"re_source": True, "skip_selected": request.skip_selected} if request.re_source and not approve else {}), **({"override": override} if override else {}),
                **({"supplier_changed_from": chosen["from"], "supplier_changed_to": chosen["to"]} if chosen else {})},
    )
    return ApprovalResponse(**result)
