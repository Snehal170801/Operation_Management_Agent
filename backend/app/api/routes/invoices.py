from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import invoice_controller
from app.models.auth_schemas import CurrentUser
from app.models.invoice_schemas import InvoiceDecisionRequest, InvoiceResponse, SubmitInvoiceRequest

# Staff only (see main.py): viewing needs cases:read_all; entering or deciding an invoice needs invoices:decide (Accounts).
router = APIRouter(tags=["invoices"])


@router.get("/invoices", response_model=list[InvoiceResponse])
def list_invoices(status: Optional[str] = None):
    """Use ?status=mismatch for invoices waiting on a person."""
    return invoice_controller.list_invoices(status)


@router.get("/cases/{case_id}/invoices", response_model=list[InvoiceResponse])
def get_case_invoices(case_id: str):
    return invoice_controller.get_case_invoices(case_id)


@router.post("/cases/{case_id}/invoices", response_model=InvoiceResponse)
def submit_invoice(case_id: str, request: SubmitInvoiceRequest, user: CurrentUser = Depends(require_permission("invoices:decide"))):
    return invoice_controller.submit_invoice(case_id, request, user)


@router.post("/invoices/{invoice_id}/approve", response_model=InvoiceResponse)
def approve_invoice(invoice_id: str, request: InvoiceDecisionRequest, user: CurrentUser = Depends(require_permission("invoices:decide"))):
    return invoice_controller.decide(invoice_id, True, request, user)


@router.post("/invoices/{invoice_id}/reject", response_model=InvoiceResponse)
def reject_invoice(invoice_id: str, request: InvoiceDecisionRequest, user: CurrentUser = Depends(require_permission("invoices:decide"))):
    return invoice_controller.decide(invoice_id, False, request, user)
