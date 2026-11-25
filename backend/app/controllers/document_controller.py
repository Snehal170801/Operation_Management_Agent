from app.agents import approval_agent, operations_agent, purchase_order_agent, vendor_agent
from app.core import audit, documents, pdf_render
from app.core.config import settings
from app.core.exceptions import ApprovalNotFound
from app.models.auth_schemas import CurrentUser
from app.orchestrator import case_pipeline


def _company() -> dict:
    return {"name": settings.COMPANY_NAME, "address": [x.strip() for x in settings.COMPANY_ADDRESS.split("|") if x.strip()]}


def _audit(action: str, case_id: str, user: CurrentUser) -> None:
    audit.record(action, actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id)


def purchase_order_pdf(case_id: str, user: CurrentUser) -> tuple[bytes, str]:
    """The purchase order for this case as a PDF, and a file name. PurchaseOrderNotFound (404) until one has been issued."""
    po = purchase_order_agent.get_purchase_order(case_id)
    vendor = next((v for v in vendor_agent.get_all_vendors() if v["vendor_id"] == po.get("vendor_id")), None)
    case = operations_agent.get_case_status(case_id)
    doc = documents.purchase_order(po, vendor, _company(), case["case_number"], case.get("requester_id"))
    _audit("document.po_pdf", case_id, user)
    return pdf_render.render_purchase_order(doc), documents.file_name("PO", po["po_number"])


def _supplier_decision(case_id: str) -> dict:
    """The supplier choice for the case: the newest one that was not replaced by a later round (price-change questions are not it)."""
    rows = [a for a in approval_agent.get_approvals(case_id=case_id) if a["approval_type"] != "price_change"]
    live = [a for a in rows if a["status"] != "superseded"] or rows
    if not live:
        raise ApprovalNotFound(case_id)
    return max(live, key=lambda a: a["created_at"])


def approval_summary_pdf(case_id: str, user: CurrentUser) -> tuple[bytes, str]:
    """One page: request, offers, the AI's reasoning and the decision. ApprovalNotFound (404) when no supplier choice has been prepared."""
    approval = _supplier_decision(case_id)
    review = case_pipeline.approval_review(approval["approval_id"])
    po = purchase_order_agent.find_purchase_order(case_id)
    doc = documents.approval_summary(review, approval, _company(), po["po_number"] if po else None)
    _audit("document.approval_summary", case_id, user)
    return pdf_render.render_approval_summary(doc), documents.file_name("Approval", review.get("case_number"))
