from datetime import datetime
from typing import Optional

from typing import Literal

from pydantic import BaseModel, Field


class UpsertVendorRequest(BaseModel):
    name: str
    reliability_score: float = 3.0
    email: Optional[str] = None
    # Phone to ring after we email them, with country code (+91...). Empty keeps what is on file.
    phone: Optional[str] = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    # Language the call is spoken in: Hindi, Marathi or English.
    call_language: Optional[Literal["hi", "mr", "en"]] = None


class UpdateVendorRequest(BaseModel):
    """Every detail of one supplier, as it should be after the change (an empty e-mail or phone clears it)."""
    name: str = Field(min_length=1, max_length=200)
    reliability_score: float = Field(ge=0, le=5)
    email: Optional[str] = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: Optional[str] = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    call_language: Literal["hi", "mr", "en"] = "hi"


class VendorResponse(BaseModel):
    vendor_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    call_language: str = "hi"
    reliability_score: float
    created_at: datetime
    # Set when the mail server said our emails to this address do not arrive; cleared when the address is changed
    email_bounced_at: Optional[datetime] = None
    email_bounce_reason: Optional[str] = None


class RfqResponse(BaseModel):
    rfq_id: str
    case_id: str
    vendor_id: str
    vendor_name: str
    status: str
    sent_at: datetime
    last_contacted_at: datetime
    reminder_count: int
    deadline_at: datetime
    replied_at: Optional[datetime] = None


class SubmitQuoteRequest(BaseModel):
    vendor_id: str
    raw_quote_text: str


class QuoteResponse(BaseModel):
    quote_id: str
    case_id: str
    vendor_id: str
    vendor_name: str
    raw_quote_text: str
    price: Optional[float] = None
    lead_time_days: Optional[int] = None
    terms: Optional[str] = None
    created_at: datetime


class VendorSelectionResponse(BaseModel):
    case_id: str
    vendor_id: str
    vendor_name: str
    rationale: Optional[str] = None
    created_at: datetime
