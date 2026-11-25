from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SharedItem(BaseModel):
    item: str
    primary_qty: int
    secondary_qty: int


class CombineSuggestion(BaseModel):
    """Two requests for the same item. The older one ("keep") carries on; the newer one ("fold") is folded into it."""
    keep_case_id: str
    keep_number: Optional[str] = None
    fold_case_id: str
    fold_number: Optional[str] = None
    matches: list[SharedItem]
    since: datetime


class CombineRequest(BaseModel):
    other_case_id: str


class CombineResult(BaseModel):
    primary_case_id: str
    closed_case_id: str
