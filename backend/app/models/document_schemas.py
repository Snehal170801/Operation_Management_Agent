from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UnmatchedDocument(BaseModel):
    document_id: str
    from_email: str
    vendor_name: Optional[str] = None
    subject: str = ""
    summary: str = ""
    file_names: list[str] = []
    status: str
    created_at: datetime


class AttachDocumentRequest(BaseModel):
    case_id: str = Field(min_length=36, max_length=36)


class AttachDocumentResponse(BaseModel):
    outcome: str


class DismissDocumentRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)
