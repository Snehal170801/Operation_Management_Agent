from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permission
from app.controllers import document_store_controller
from app.models.auth_schemas import CurrentUser
from app.models.document_store_schemas import DocumentPage

# Open to anyone who may read cases, but each controller call scopes what is returned: staff see everything, a requester only a sanitised view
# of their own cases (core/document_index.for_requester).
router = APIRouter(tags=["document-store"])
_can_read = require_permission("cases:read")


@router.get("/document-store", response_model=DocumentPage)
def search(q: Optional[str] = Query(default=None, max_length=100), kind: Optional[str] = Query(default=None, max_length=20),
           limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=100000), user: CurrentUser = Depends(_can_read)):
    """Search every purchase order, invoice, quote and received file (case number, supplier, number, amount, status)."""
    return document_store_controller.search(user, q, kind, limit, offset)


@router.get("/cases/{case_id}/document-store", response_model=DocumentPage)
def for_case(case_id: str, user: CurrentUser = Depends(_can_read)):
    return document_store_controller.for_case(user, case_id)
