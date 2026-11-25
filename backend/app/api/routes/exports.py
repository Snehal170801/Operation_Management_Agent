from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import require_permission
from app.controllers import export_controller
from app.core import exports
from app.models.auth_schemas import CurrentUser

# Each route names its own permission (see app/core/permissions.py): cases for anyone who may read cases (a requester gets only their own),
# purchase orders and invoices for staff who may view all, stock for whoever may read stock.
router = APIRouter(prefix="/exports", tags=["exports"])


def _csv(kind: str, user: CurrentUser, fmt: str = "csv") -> Response:
    content, name = export_controller.export(kind, user, fmt)
    media = exports.XLSX_TYPE if fmt == "xlsx" else "text/csv; charset=utf-8"
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/cases.csv")
def cases_csv(user: CurrentUser = Depends(require_permission("cases:read"))):
    return _csv("cases", user)


@router.get("/purchase-orders.csv")
def purchase_orders_csv(user: CurrentUser = Depends(require_permission("cases:read_all"))):
    return _csv("purchase-orders", user)


@router.get("/invoices.csv")
def invoices_csv(user: CurrentUser = Depends(require_permission("cases:read_all"))):
    return _csv("invoices", user)


@router.get("/stock.csv")
def stock_csv(user: CurrentUser = Depends(require_permission("stock:read"))):
    return _csv("stock", user)


# The same four as Excel workbooks, with the same permissions.
@router.get("/cases.xlsx")
def cases_xlsx(user: CurrentUser = Depends(require_permission("cases:read"))):
    return _csv("cases", user, "xlsx")


@router.get("/purchase-orders.xlsx")
def purchase_orders_xlsx(user: CurrentUser = Depends(require_permission("cases:read_all"))):
    return _csv("purchase-orders", user, "xlsx")


@router.get("/invoices.xlsx")
def invoices_xlsx(user: CurrentUser = Depends(require_permission("cases:read_all"))):
    return _csv("invoices", user, "xlsx")


@router.get("/stock.xlsx")
def stock_xlsx(user: CurrentUser = Depends(require_permission("stock:read"))):
    return _csv("stock", user, "xlsx")
