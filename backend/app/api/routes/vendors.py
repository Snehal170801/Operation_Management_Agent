from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.controllers import vendor_controller
from app.models.auth_schemas import CurrentUser
from app.models.vendor_schemas import (
    UpdateVendorRequest,
    UpsertVendorRequest,
    VendorResponse,
    SubmitQuoteRequest,
    QuoteResponse,
    RfqResponse,
    VendorSelectionResponse,
)

router = APIRouter(tags=["vendors"])


@router.get("/vendors", response_model=list[VendorResponse])
def get_all_vendors():
    return vendor_controller.get_all_vendors()


@router.post("/vendors", status_code=204)
def upsert_vendor(request: UpsertVendorRequest):
    vendor_controller.upsert_vendor(request)


@router.put("/vendors/{vendor_id}", status_code=204)
def update_vendor(vendor_id: str, request: UpdateVendorRequest, user: CurrentUser = Depends(get_current_user)):
    """Edit one supplier's details (name, e-mail, phone, call language, reliability). 404 for an unknown supplier, 422 for a name or
    e-mail another supplier already has."""
    vendor_controller.update_vendor(vendor_id, request, user)


@router.post("/cases/{case_id}/quotes", response_model=QuoteResponse)
def submit_quote(case_id: str, request: SubmitQuoteRequest):
    return vendor_controller.submit_quote(case_id, request)


@router.get("/cases/{case_id}/rfqs", response_model=list[RfqResponse])
def get_rfqs(case_id: str):
    return vendor_controller.get_rfqs(case_id)


@router.get("/cases/{case_id}/quotes", response_model=list[QuoteResponse])
def get_quotes(case_id: str):
    return vendor_controller.get_quotes(case_id)


@router.post("/cases/{case_id}/rank-vendors", response_model=VendorSelectionResponse)
def rank_vendors(case_id: str):
    return vendor_controller.rank_vendors(case_id)


@router.get("/cases/{case_id}/vendor-selection", response_model=VendorSelectionResponse)
def get_vendor_selection(case_id: str):
    return vendor_controller.get_vendor_selection(case_id)
