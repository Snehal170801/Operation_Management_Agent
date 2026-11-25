from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class DecisionOption(BaseModel):
    vendor_name: str
    price: Optional[float] = None
    lead_time_days: Optional[int] = None
    terms: Optional[str] = None
    tags: list[str] = []


class DecisionPriceChange(BaseModel):
    po_number: Optional[str] = None
    vendor_name: Optional[str] = None
    agreed_total: Optional[float] = None
    new_total: Optional[float] = None
    pct: Optional[float] = None


class DecisionInfo(BaseModel):
    """What the page shows before anyone taps anything. No supplier contact details, nothing the approver would not see in the email."""
    kind: str                                     # vendor_selection | price_change
    case_number: Optional[str] = None
    recipient: str
    request_text: Optional[str] = None
    items: list[dict] = []
    reasons: list[str] = []
    urgent: bool = False
    needed_by: Optional[date] = None
    chosen: Optional[DecisionOption] = None
    other_offers: int = 0
    price_change: Optional[DecisionPriceChange] = None
    expires_at: datetime
    can_decide: bool = True
    blocked: Optional[str] = None                 # why this person cannot decide it (their own request, say)


class DecisionRequest(BaseModel):
    action: str = Field(pattern="^(approve|refuse)$")
    note: Optional[str] = Field(default=None, max_length=500)


class DecisionResult(BaseModel):
    outcome: str                                  # approved | refused
    case_number: Optional[str] = None
    message: str
