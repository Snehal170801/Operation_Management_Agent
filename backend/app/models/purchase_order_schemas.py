from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class PurchaseOrderItem(BaseModel):
    description: str
    quantity: int


class PurchaseOrderListItem(BaseModel):
    """One row of the Purchase orders page."""
    purchase_order_id: str
    po_number: str
    case_id: str
    case_number: Optional[str] = None
    vendor_name: str
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    total_with_tax: Optional[float] = None
    status: str
    delivery_status: Optional[str] = None
    expected_delivery_date: Optional[date] = None
    created_at: datetime
    sent_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class PurchaseOrderResponse(BaseModel):
    purchase_order_id: str
    po_number: str
    case_id: str
    vendor_id: str
    vendor_name: str
    total_amount: Optional[float] = None
    # Tax lines, when a tax rate is set (null otherwise): the order is total_amount plus tax_amount = total_with_tax (or total_amount already includes it).
    tax_rate_pct: Optional[float] = None
    tax_amount: Optional[float] = None
    total_with_tax: Optional[float] = None
    lead_time_days: Optional[int] = None
    terms: Optional[str] = None
    expected_delivery_date: Optional[date] = None
    items: list[PurchaseOrderItem]
    status: str
    created_at: datetime
    sent_at: Optional[datetime] = None
    # Whether the supplier has confirmed they have the order
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    confirm_chase_count: int = 0
    last_confirm_chase_at: Optional[datetime] = None
    confirm_escalated_at: Optional[datetime] = None
    # What the supplier said was wrong with the order, until a person sorts it out
    vendor_issue: Optional[str] = None
    # Asking the supplier to cancel the order
    cancel_requested_at: Optional[datetime] = None
    cancel_requested_by: Optional[str] = None
    cancel_reason: Optional[str] = None
    cancel_chase_count: int = 0
    cancel_escalated_at: Optional[datetime] = None
    cancel_refused_at: Optional[datetime] = None


class ConfirmPurchaseOrderRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)
