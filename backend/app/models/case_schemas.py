from datetime import date, datetime
from typing import Optional, Any

from pydantic import BaseModel, Field


class CreateCaseRequest(BaseModel):
    # Ignored for requesters (always themselves); staff may file a request on someone's behalf.
    requester_id: Optional[str] = Field(default=None, max_length=100)
    raw_request: str = Field(min_length=1, max_length=2000)
    # When the goods are needed by, and whether the request is urgent. Both optional; the text may also say it.
    needed_by: Optional[date] = None
    urgent: bool = False


class CreateCaseResponse(BaseModel):
    case_id: str


class CaseStatusResponse(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    requester_id: str
    stage: str
    status: str
    summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CaseListItemResponse(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    requester_id: str
    stage: str
    status: str
    item_count: Optional[int] = None
    total_quantity: Optional[int] = None
    items_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    urgent: bool = False
    needed_by: Optional[date] = None


class CaseEventResponse(BaseModel):
    event_id: int
    event_type: str
    agent_name: Optional[str] = None
    payload: Optional[Any] = None
    label: Optional[str] = None          # plain-English line for staff (None for requesters, who see the page's own wording)
    created_at: datetime
