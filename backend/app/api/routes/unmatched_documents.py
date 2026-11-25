from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.controllers import unmatched_document_controller
from app.core import access
from app.core.exceptions import Forbidden
from app.models.auth_schemas import CurrentUser
from app.models.document_schemas import AttachDocumentRequest, AttachDocumentResponse, DismissDocumentRequest, UnmatchedDocument

# Every staff member may see the list (the router's cases:read_all guard); only Accounts and the Vendor team (and admins) act on it.
router = APIRouter(prefix="/documents", tags=["documents"])

HANDLERS = ("invoices:decide", "vendors:write")


def _handler(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not any(access.has_permission(user.role, p) for p in HANDLERS):
        raise Forbidden()
    return user


@router.get("/unmatched", response_model=list[UnmatchedDocument])
def list_unmatched():
    return unmatched_document_controller.list_unmatched()


@router.post("/unmatched/{document_id}/attach", response_model=AttachDocumentResponse)
def attach(document_id: str, request: AttachDocumentRequest, user: CurrentUser = Depends(_handler)):
    return unmatched_document_controller.attach(document_id, request, user)


@router.post("/unmatched/{document_id}/dismiss", status_code=204)
def dismiss(document_id: str, request: DismissDocumentRequest, user: CurrentUser = Depends(_handler)):
    unmatched_document_controller.dismiss(document_id, request, user)
