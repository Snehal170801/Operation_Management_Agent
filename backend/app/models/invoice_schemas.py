from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SubmitInvoiceRequest(BaseModel):
    """Paste the invoice text (e.g. copied from the vendor's email) for the agent to read and match."""
    raw_text: str = Field(min_length=1, max_length=8000)


class InvoiceDecisionRequest(BaseModel):
    # Who decided is taken from the signed-in user, not from the request.
    note: Optional[str] = Field(default=None, max_length=1000)


class InvoiceResponse(BaseModel):
    invoice_id: str
    case_id: str
    purchase_order_id: str
    vendor_id: str
    vendor_name: str
    po_number: str
    case_number: Optional[str] = None            # filled on the invoice list (the Invoices page)
    invoice_number: Optional[str] = None
    total_amount: Optional[float] = None
    # What the invoice showed for tax (null when it showed none)
    subtotal: Optional[float] = None
    tax_rate_pct: Optional[float] = None
    tax_amount: Optional[float] = None
    # matched | on_hold | mismatch | approved | rejected
    status: str
    issues: list[str]
    source: str
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None
    # One sentence on whether it matches and what to do, and its verdict: match | waiting | mismatch | check
    suggestion: Optional[str] = None
    verdict: Optional[str] = None
