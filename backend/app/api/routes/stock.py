from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.controllers import stock_controller
from app.models.auth_schemas import CurrentUser
from app.models.stock_schemas import (
    ReorderRequest,
    ReorderResponse,
    StockHistoryEntry,
    StockItemResponse,
    StockLevelsRequest,
    UpdateStockItemRequest,
    UpsertStockRequest,
)

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("", response_model=list[StockItemResponse])
def get_all_stock():
    return stock_controller.get_all_stock()


@router.post("", status_code=204)
def upsert_stock(request: UpsertStockRequest, user: CurrentUser = Depends(get_current_user)):
    """Add an item or set its count. The change is recorded in the item's history against the signed-in person."""
    stock_controller.upsert_stock(request, user)


@router.get("/history", response_model=list[StockHistoryEntry])
def stock_history(item: str):
    """Every change to one item's count: who, when, old and new value, why and the case. Newest first."""
    return stock_controller.get_history(item)


@router.patch("/item", status_code=204)
def update_item(request: UpdateStockItemRequest, user: CurrentUser = Depends(get_current_user)):
    """Rename an item or change its unit, category or preferred supplier."""
    stock_controller.update_item(request, user)


@router.delete("/item", status_code=204)
def remove_item(item: str, user: CurrentUser = Depends(get_current_user)):
    """Remove an item. Refused (409) while an open order or request refers to it."""
    stock_controller.remove_item(item, user)


@router.put("/levels", status_code=204)
def set_levels(request: StockLevelsRequest, user: CurrentUser = Depends(get_current_user)):
    """When an item counts as low and what to order up to. Whoever may change stock (Stores, admin): the router's stock:write guard."""
    stock_controller.set_levels(request, user)


@router.post("/reorder", response_model=ReorderResponse)
def reorder(request: ReorderRequest, user: CurrentUser = Depends(get_current_user)):
    """Order more of an item that is running low. Same flow as any request."""
    return stock_controller.reorder(request, user)
