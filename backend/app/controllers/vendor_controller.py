from app.agents import vendor_agent
from app.core import audit
from app.models.auth_schemas import CurrentUser
from app.orchestrator import case_pipeline
from app.models.vendor_schemas import (
    UpdateVendorRequest,
    UpsertVendorRequest,
    VendorResponse,
    SubmitQuoteRequest,
    QuoteResponse,
    RfqResponse,
    VendorSelectionResponse,
)


def get_all_vendors() -> list[VendorResponse]:
    return [VendorResponse(**v) for v in vendor_agent.get_all_vendors()]


def upsert_vendor(request: UpsertVendorRequest) -> None:
    vendor_agent.upsert_vendor(request.name, request.reliability_score, request.email, request.phone, request.call_language)


def update_vendor(vendor_id: str, request: UpdateVendorRequest, user: CurrentUser) -> None:
    """Edit a supplier's details. Only what actually changed is written to the audit log."""
    email = (request.email or "").strip() or None
    before = vendor_agent.update_vendor(vendor_id, request.name, email, request.phone or None, request.call_language, request.reliability_score)
    after = {"name": request.name.strip(), "email": email, "phone": request.phone or None, "call_language": request.call_language,
             "reliability_score": request.reliability_score}
    changes = {k: {"from": before.get(k), "to": v} for k, v in after.items() if (before.get(k) or None) != (v or None)}
    audit.record("vendor.update", actor_user_id=user.user_id, actor_username=user.username, target_type="vendor", target_id=before["vendor_id"],
                 detail={"name": before["name"], "changes": changes})


def submit_quote(case_id: str, request: SubmitQuoteRequest) -> QuoteResponse:
    result = vendor_agent.submit_quote(case_id, request.vendor_id, request.raw_quote_text)
    return QuoteResponse(**result)


def get_rfqs(case_id: str) -> list[RfqResponse]:
    return [RfqResponse(**r) for r in vendor_agent.get_rfqs(case_id)]


def get_quotes(case_id: str) -> list[QuoteResponse]:
    return [QuoteResponse(**q) for q in vendor_agent.get_quotes(case_id)]


def rank_vendors(case_id: str) -> VendorSelectionResponse:
    result = case_pipeline.rank_and_review(case_id)
    return VendorSelectionResponse(**result)


def get_vendor_selection(case_id: str) -> VendorSelectionResponse:
    result = vendor_agent.get_vendor_selection(case_id)
    return VendorSelectionResponse(**result)
