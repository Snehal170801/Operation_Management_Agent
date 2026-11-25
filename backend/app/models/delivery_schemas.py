from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeliveryLine(BaseModel):
    description: str
    ordered: int
    received: int
    outstanding: int


class DeliveryBatch(BaseModel):
    at: Optional[str] = None
    by: Optional[str] = None
    note: Optional[str] = None
    items: dict[str, int] = {}


class ConfirmDeliveryRequest(BaseModel):
    # Who received it is taken from the signed-in user.
    note: Optional[str] = Field(default=None, max_length=1000)
    # What arrived, by item name. Leave out to receive everything still owed.
    items: Optional[dict[str, int]] = None


class ShortCloseRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


class DeliveryResponse(BaseModel):
    case_id: str
    po_number: str
    vendor_name: str
    expected_delivery_date: Optional[date] = None
    delivery_status: str
    delivered_at: Optional[datetime] = None
    received_by: Optional[str] = None
    delivery_note: Optional[str] = None
    chase_count: int
    last_chased_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    # Part deliveries: one line per ordered item, and the batches received so far
    items: list["DeliveryLine"] = []
    batches: list["DeliveryBatch"] = []
    received_units: int = 0
    ordered_units: int = 0
    partial: bool = False
    short_closed_at: Optional[datetime] = None


class ReceiptResponse(BaseModel):
    """The requester's own answer to "did the goods reach you?"."""
    state: str  # not_delivered | ask | confirmed | disputed | followed_up
    note: Optional[str] = None
    at: Optional[datetime] = None


class ReceiptRequest(BaseModel):
    received: bool
    note: Optional[str] = Field(default=None, max_length=500)


class DisputeHandledRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)
