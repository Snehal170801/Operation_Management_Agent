from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AffectedItem(BaseModel):
    description: str
    quantity: int


class GoodsIssue(BaseModel):
    issue_id: str
    case_id: str
    po_number: str
    vendor_name: str
    kind: str
    items: list[AffectedItem]
    description: Optional[str] = None
    reported_by: str
    reported_at: datetime
    status: str                                  # open | resolved
    supplier_told_at: Optional[datetime] = None
    supplier_replied_at: Optional[datetime] = None
    chase_count: int = 0
    escalated_at: Optional[datetime] = None
    resolution: Optional[str] = None             # replaced | credit | accepted
    credit_amount: Optional[float] = None
    resolution_note: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    # Returning the goods and waiting for a replacement (tracking only)
    return_status: Optional[str] = None          # returned
    return_ref: Optional[str] = None
    returned_at: Optional[datetime] = None
    returned_by: Optional[str] = None
    replacement_status: Optional[str] = None     # expected | received
    replacement_expected_at: Optional[datetime] = None
    replacement_received_at: Optional[datetime] = None
    credit_note_number: Optional[str] = None


class ReportIssueRequest(BaseModel):
    kind: str = Field(pattern="^(damaged|wrong_item|not_as_described|other)$")
    # Which items and how many are affected. Leave out for everything that has arrived.
    items: Optional[dict[str, int]] = None
    description: Optional[str] = Field(default=None, max_length=500)


class ResolveIssueRequest(BaseModel):
    resolution: str = Field(pattern="^(replaced|credit|accepted)$")
    credit_amount: Optional[float] = Field(default=None, gt=0)
    credit_note_number: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=500)


class ReturnIssueRequest(BaseModel):
    ref: Optional[str] = Field(default=None, max_length=100)


class ReplacementReceivedRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)
