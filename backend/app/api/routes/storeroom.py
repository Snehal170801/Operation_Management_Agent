from typing import Optional

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import require_permission
from app.controllers import storeroom_controller
from app.models.auth_schemas import CurrentUser
from app.models.storeroom_schemas import DatasetPage, StoreRoomOverview

# Read-only. Every dataset is defined in app/core/storeroom_catalog.py; callers choose a dataset by key
# and can only add a search term, which is passed to the database as a parameter.
router = APIRouter(prefix="/store-room", tags=["store-room"])

_guard = require_permission("storeroom:read")


@router.get("", response_model=StoreRoomOverview)
def overview(_: CurrentUser = Depends(_guard)):
    return storeroom_controller.get_overview()


@router.get("/{dataset}", response_model=DatasetPage)
def dataset_page(
    dataset: str,
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: CurrentUser = Depends(_guard),
):
    return storeroom_controller.get_page(dataset, search, limit, offset)


@router.get("/{dataset}/export")
def dataset_export(
    dataset: str,
    search: Optional[str] = Query(None, max_length=100),
    user: CurrentUser = Depends(_guard),
):
    """The whole dataset (up to 10,000 rows, filtered by the search) as a CSV file."""
    filename, content = storeroom_controller.export_csv(dataset, search, user)
    return Response(
        content="﻿" + content,   # byte-order mark so Excel opens it as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
