from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import goods_issue_controller
from app.models.auth_schemas import CurrentUser
from app.models.goods_issue_schemas import GoodsIssue, ReplacementReceivedRequest, ReportIssueRequest, ResolveIssueRequest, ReturnIssueRequest

# Staff only (the list is read with cases:read_all, changes need delivery:confirm). A requester never sees supplier or money details.
router = APIRouter(prefix="/cases/{case_id}/goods-issues", tags=["goods-issues"])


@router.get("", response_model=list[GoodsIssue], dependencies=[Depends(require_permission("cases:read_all"))])
def list_issues(case_id: str):
    return goods_issue_controller.list_issues(case_id)


@router.post("", response_model=GoodsIssue)
def report(case_id: str, request: ReportIssueRequest, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """Record a problem with goods that arrived (damaged, wrong item...). The supplier is asked to put it right and payment is held."""
    return goods_issue_controller.report(case_id, request.kind, request.items, request.description, user)


@router.post("/{issue_id}/resolve", response_model=GoodsIssue)
def resolve(case_id: str, issue_id: str, request: ResolveIssueRequest, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """Record how the problem ended: replaced, a credit of an agreed amount, or accepted as it is."""
    return goods_issue_controller.resolve(case_id, issue_id, request.resolution, request.credit_amount, request.note, user, request.credit_note_number)


@router.post("/{issue_id}/return", response_model=GoodsIssue)
def return_goods(case_id: str, issue_id: str, request: ReturnIssueRequest, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """The faulty goods are going back to the supplier: recorded, and the supplier is told what is coming. Stock and money are not changed."""
    return goods_issue_controller.return_goods(case_id, issue_id, request.ref, user)


@router.post("/{issue_id}/replacement-expected", response_model=GoodsIssue)
def replacement_expected(case_id: str, issue_id: str, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """The supplier promised replacements. The problem stays open (payment stays held) and the reminders stop."""
    return goods_issue_controller.expect_replacement(case_id, issue_id, user)


@router.post("/{issue_id}/replacement-received", response_model=GoodsIssue)
def replacement_received(case_id: str, issue_id: str, request: ReplacementReceivedRequest, user: CurrentUser = Depends(require_permission("delivery:confirm"))):
    """The replacement arrived: the problem ends as 'replaced' (stock goes back for a reorder, a held invoice is checked again)."""
    return goods_issue_controller.receive_replacement(case_id, issue_id, request.note, user)
