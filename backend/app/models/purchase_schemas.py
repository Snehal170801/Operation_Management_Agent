from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CreatePurchaseRequestRequest(BaseModel):
    case_id: str
    raw_request: str


class PurchaseRequestItemResponse(BaseModel):
    description: str
    quantity: int


class PurchaseRequestResponse(BaseModel):
    purchase_request_id: str
    case_id: str
    cost_center: Optional[str] = None
    raw_request: str
    items: list[PurchaseRequestItemResponse]
    created_at: datetime
    needed_by: Optional[date] = None
    urgent: bool = False
