from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class UpsertStockRequest(BaseModel):
    item_description: str
    quantity_available: int


class OpenOrder(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    quantity: Optional[int] = None


class StockItemResponse(BaseModel):
    item_description: str
    quantity_available: int
    updated_at: datetime
    min_level: Optional[int] = None
    target_level: Optional[int] = None
    low: bool = False
    suggested_quantity: Optional[int] = None
    open_order: Optional[OpenOrder] = None            # a re-order for this item that is still in progress
    unit: Optional[str] = None
    category: Optional[str] = None
    preferred_vendor_id: Optional[str] = None
    preferred_vendor_name: Optional[str] = None       # the supplier that is always asked for a quote on this item


class StockHistoryEntry(BaseModel):
    entry_id: str
    item_description: str
    old_quantity: int
    new_quantity: int
    change: int
    reason: str
    reason_label: str
    actor: str
    by_a_person: bool
    case_id: Optional[str] = None
    case_number: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime


class UpdateStockItemRequest(BaseModel):
    """Change an item's details. The counts and levels have their own requests. Leave `new_description` out to keep the name."""
    item_description: str                             # which item (its current name)
    new_description: Optional[str] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    preferred_vendor_id: Optional[str] = None         # empty clears it


class StockLevelsRequest(BaseModel):
    item_description: str
    min_level: Optional[int] = Field(default=None, ge=0)
    target_level: Optional[int] = Field(default=None, ge=0)


class ReorderRequest(BaseModel):
    item_description: str
    quantity: int = Field(gt=0)
    needed_by: Optional[date] = None
    urgent: bool = False


class ReorderResponse(BaseModel):
    case_id: str
    case_number: Optional[str] = None
