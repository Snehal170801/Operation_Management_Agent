from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChangeLine(BaseModel):
    item: str
    # `from` is a Python keyword, so these travel as from_ / to
    from_: int = Field(alias="from")
    to: int

    model_config = {"populate_by_name": True}


class PendingChange(BaseModel):
    changes: list[ChangeLine]
    by: Optional[str] = None
    note: Optional[str] = None
    at: datetime


class RequestItem(BaseModel):
    description: str
    quantity: int


class ChangeOptions(BaseModel):
    """What the person may do to this request right now."""
    phase: str                  # before_order | after_order | cancelling | delivered | from_stock | closed
    can_cancel: bool
    can_change: bool
    note: str
    items: list[RequestItem] = []
    pending_change: Optional[PendingChange] = None


class CancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class ChangeRequest(BaseModel):
    # New quantity by item name; only the items that change need to be listed.
    quantities: dict[str, int]
    note: Optional[str] = Field(default=None, max_length=500)


class ChangeOutcome(BaseModel):
    outcome: str
    suppliers_told: list[str] = []


class ResolveCancelRequest(BaseModel):
    action: str = Field(pattern="^(settled|carry_on)$")
    note: Optional[str] = Field(default=None, max_length=500)


class ResolveChangeRequest(BaseModel):
    action: str = Field(pattern="^(amended|declined)$")
    total_amount: Optional[float] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=500)
