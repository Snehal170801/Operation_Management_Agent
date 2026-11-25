from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class DecideApprovalRequest(BaseModel):
    # Who decided is taken from the signed-in user, not from the request.
    note: Optional[str] = Field(default=None, max_length=1000)
    # Approving: the supplier the person chose. Leave out to go with the one currently selected (the AI's pick).
    vendor_id: Optional[str] = Field(default=None, max_length=64)
    # Rejecting: ask the suppliers for new quotes instead of ending the request.
    re_source: bool = False
    # With re_source: do not ask the supplier who was selected this time.
    skip_selected: bool = False


class ApprovalResponse(BaseModel):
    approval_id: str
    case_id: str
    case_number: Optional[str] = None
    approval_type: str
    status: str
    reasons: list[str]
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class ReviewItem(BaseModel):
    description: str
    quantity: int


class ReviewOption(BaseModel):
    """One supplier, as the approver sees it."""
    rank: Optional[int] = None
    vendor_id: str
    vendor_name: str
    email: Optional[str] = None
    price: Optional[float] = None
    lead_time_days: Optional[int] = None
    terms: Optional[str] = None
    reliability: Optional[float] = None
    # What the supplier wrote, in their own words
    reply_text: str = ""
    # The AI's reason for this supplier's place in the ranking
    reason: Optional[str] = None
    tags: list[str] = []


class PriceChange(BaseModel):
    """A supplier asking for a higher price on an order already placed."""
    po_number: Optional[str] = None
    vendor_name: Optional[str] = None
    agreed_total: Optional[float] = None
    new_total: Optional[float] = None
    pct: Optional[float] = None
    reply_text: str = ""


class NegotiationNote(BaseModel):
    """The supplier was asked once for a better price: what came of it (see core/negotiation.py)."""
    vendor: str
    outcome: str                                # waiting | improved | kept | no_reply
    original_price: Optional[float] = None
    new_price: Optional[float] = None
    saving: Optional[float] = None
    text: str


class ApprovalReview(BaseModel):
    kind: str = "vendor_selection"          # vendor_selection | price_change
    price_change: Optional[PriceChange] = None
    approval_id: str
    case_id: str
    case_number: Optional[str] = None
    status: str
    reasons: list[str]
    requested_by: Optional[str] = None
    request_text: Optional[str] = None
    items: list[ReviewItem] = []
    recommended_vendor_id: Optional[str] = None
    selected_vendor_id: Optional[str] = None
    rationale: Optional[str] = None
    # One sentence: what to do, and what the other suppliers offer
    suggestion: Optional[str] = None
    options: list[ReviewOption] = []
    negotiation: Optional[NegotiationNote] = None
    # Quotes can be asked for again after a rejection (see core/resource_policy.py)
    round: int = 1
    earlier_note: Optional[str] = None
    can_ask_again: bool = False
    # An urgent request, and the date the goods are needed by
    urgent: bool = False
    needed_by: Optional[date] = None
