from fastapi import APIRouter

from app.controllers import purchase_order_controller
from app.models.purchase_order_schemas import PurchaseOrderListItem

# Staff only (see main.py: cases:read_all). Every purchase order, newest first, for the Purchase orders page.
router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


@router.get("", response_model=list[PurchaseOrderListItem])
def list_purchase_orders():
    return purchase_order_controller.list_purchase_orders()
