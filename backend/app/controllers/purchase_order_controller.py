from app.agents import operations_agent, purchase_order_agent
from app.core import audit
from app.models.auth_schemas import CurrentUser
from app.models.purchase_order_schemas import PurchaseOrderListItem, PurchaseOrderResponse
from app.orchestrator import case_pipeline


def list_purchase_orders() -> list[PurchaseOrderListItem]:
    numbers = {c["case_id"].lower(): c["case_number"] for c in operations_agent.get_all_cases(None)}
    return [PurchaseOrderListItem(**{**p, "case_number": numbers.get(p["case_id"].lower())}) for p in purchase_order_agent.list_purchase_orders()]


def get_purchase_order(case_id: str) -> PurchaseOrderResponse | None:
    """None (an ordinary answer, not an error) while no order has been issued: the page shows "no order yet" and the browser console stays
    clean. A case that does not exist is still CaseNotFound (404)."""
    po = purchase_order_agent.find_purchase_order(case_id)
    if po is None:
        operations_agent.get_case_status(case_id)
        return None
    return PurchaseOrderResponse(**po)


def issue_purchase_order(case_id: str) -> PurchaseOrderResponse:
    """Manual retry for a case whose automatic PO step failed. Safe to repeat: one PO per case."""
    return PurchaseOrderResponse(**case_pipeline.issue_purchase_order(case_id))


def confirm_purchase_order(case_id: str, note: str | None, user: CurrentUser) -> PurchaseOrderResponse:
    """A person records that the supplier confirmed the order another way, or that a problem they raised is sorted out."""
    result = case_pipeline.confirm_purchase_order(case_id, user.username, note)
    audit.record(
        "po.confirm", actor_user_id=user.user_id, actor_username=user.username,
        target_type="case", target_id=case_id, detail={"note": note},
    )
    return PurchaseOrderResponse(**result)
