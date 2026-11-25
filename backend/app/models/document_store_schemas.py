from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StoredDocument(BaseModel):
    id: str
    kind: str                      # purchase_order | invoice | quote | file
    kind_label: str
    title: str
    case_id: str
    case_number: Optional[str] = None
    vendor: Optional[str] = None   # None for a requester
    amount: Optional[float] = None
    status: Optional[str] = None
    at: Optional[datetime] = None


class DocumentPage(BaseModel):
    items: list[StoredDocument]
    total: int
    counts: dict[str, int]         # matches per kind, ignoring the kind filter
    limit: int
    offset: int
    sanitised: bool = False        # True for a requester: only their own cases, only "there is an order / an invoice"
