from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import get_current_user
from app.controllers import document_controller
from app.models.auth_schemas import CurrentUser

router = APIRouter(prefix="/cases/{case_id}/documents", tags=["documents"])


def _pdf(content: bytes, name: str) -> Response:
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/purchase-order.pdf")
def purchase_order_pdf(case_id: str, user: CurrentUser = Depends(get_current_user)):
    return _pdf(*document_controller.purchase_order_pdf(case_id, user))


@router.get("/approval-summary.pdf")
def approval_summary_pdf(case_id: str, user: CurrentUser = Depends(get_current_user)):
    return _pdf(*document_controller.approval_summary_pdf(case_id, user))
