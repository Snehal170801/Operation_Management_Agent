from app.agents import invoice_agent, operations_agent
from app.core import audit
from app.core.permissions import ADMIN_ROLE
from app.core.separation import check_not_the_receiver
from app.agents import delivery_agent
from app.core.exceptions import PurchaseOrderNotFound
from app.controllers.invoice_suggestions import attach_suggestions
from app.models.auth_schemas import CurrentUser
from app.models.invoice_schemas import InvoiceDecisionRequest, InvoiceResponse, SubmitInvoiceRequest
from app.orchestrator import case_pipeline


def list_invoices(status: str | None) -> list[InvoiceResponse]:
    try:
        numbers = {c["case_id"].lower(): c["case_number"] for c in operations_agent.get_all_cases(None)}
    except Exception:                                   # the case numbers are a convenience: the list itself must still work
        numbers = {}
    return [InvoiceResponse(**{**i, "case_number": numbers.get(i["case_id"].lower())}) for i in attach_suggestions(invoice_agent.list_invoices(status))]


def get_case_invoices(case_id: str) -> list[InvoiceResponse]:
    return [InvoiceResponse(**i) for i in attach_suggestions(invoice_agent.get_invoices(case_id))]


def submit_invoice(case_id: str, request: SubmitInvoiceRequest, user: CurrentUser) -> InvoiceResponse:
    invoice = case_pipeline.process_invoice(case_id, request.raw_text, source="manual")
    audit.record(
        "invoice.submit", actor_user_id=user.user_id, actor_username=user.username,
        target_type="invoice", target_id=invoice["invoice_id"],
        detail={"case_id": case_id, "status": invoice["status"]},
    )
    return InvoiceResponse(**attach_suggestions([invoice])[0])


def decide(invoice_id: str, approve: bool, request: InvoiceDecisionRequest, user: CurrentUser) -> InvoiceResponse:
    # Whoever confirmed the goods for this order may not also decide its invoice (an admin may, on the record).
    existing = invoice_agent.get_invoice(invoice_id)
    try:
        received_by = delivery_agent.get_delivery(existing["case_id"])["received_by"]
    except PurchaseOrderNotFound:
        received_by = None
    override = check_not_the_receiver(user.username, received_by, user.role == ADMIN_ROLE)

    invoice = case_pipeline.decide_invoice(invoice_id, approve, user.username, request.note)
    audit.record(
        "invoice.approve" if approve else "invoice.reject",
        actor_user_id=user.user_id, actor_username=user.username,
        target_type="invoice", target_id=invoice_id,
        detail={"case_id": invoice["case_id"], "note": request.note, **({"override": override} if override else {})},
    )
    return InvoiceResponse(**invoice)
