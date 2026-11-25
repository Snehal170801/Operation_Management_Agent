import csv
import io
import json
from decimal import Decimal

from app.core import audit
from app.core.exceptions import DatasetNotFound
from app.core.storeroom_catalog import Dataset, get_dataset, groups
from app.models.auth_schemas import CurrentUser
from app.models.storeroom_schemas import (
    ColumnInfo,
    DatasetGroup,
    DatasetPage,
    DatasetSummary,
    StoreRoomOverview,
)
from app.repositories import storeroom_repository

EXPORT_LIMIT = 10_000
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def get_overview() -> StoreRoomOverview:
    return StoreRoomOverview(groups=[
        DatasetGroup(label=label, datasets=[
            DatasetSummary(key=d.key, label=d.label, description=d.description, count=storeroom_repository.count(d))
            for d in datasets
        ])
        for label, datasets in groups()
    ])


def get_page(key: str, search: str | None, limit: int, offset: int) -> DatasetPage:
    dataset = _require(key)
    return DatasetPage(
        key=dataset.key, label=dataset.label, description=dataset.description,
        columns=[ColumnInfo(key=c.key, label=c.label, kind=c.kind) for c in dataset.columns],
        rows=_with_case_numbers(dataset, [_shape(dataset, row) for row in storeroom_repository.page(dataset, search, limit, offset)]),
        total=storeroom_repository.count(dataset, search), limit=limit, offset=offset,
    )


def export_csv(key: str, search: str | None, user: CurrentUser) -> tuple[str, str]:
    """(file name, CSV text) for the dataset, filtered by `search`, capped at EXPORT_LIMIT rows."""
    dataset = _require(key)
    rows = _with_case_numbers(dataset, [_shape(dataset, r) for r in storeroom_repository.page(dataset, search, EXPORT_LIMIT, 0)])

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([c.label for c in dataset.columns])
    for row in rows:
        writer.writerow([_csv_cell(row[c.key]) for c in dataset.columns])

    audit.record(
        "storeroom.export", actor_user_id=user.user_id, actor_username=user.username,
        target_type="dataset", target_id=dataset.key, detail={"rows": len(rows), "search": search or None},
    )
    return f"{dataset.key}.csv", out.getvalue()


def _with_case_numbers(dataset: Dataset, rows: list[dict]) -> list[dict]:
    """Case columns hold {"id", "number"}: the screen shows the readable number and links by id."""
    case_keys = [c.key for c in dataset.columns if c.kind == "case"]
    if not case_keys:
        return rows
    numbers = storeroom_repository.case_numbers([r[k] for r in rows for k in case_keys if r[k]])
    for row in rows:
        for key in case_keys:
            if row[key]:
                row[key] = {"id": row[key], "number": numbers.get(str(row[key]).lower())}
    return rows


def _require(key: str) -> Dataset:
    dataset = get_dataset(key)
    if dataset is None:
        raise DatasetNotFound(key)
    return dataset


def _shape(dataset: Dataset, row: dict) -> dict:
    """Make a database row JSON-friendly: ids as text, decimals as numbers, JSON lists as lists."""
    shaped = {}
    for column in dataset.columns:
        value = row[column.key]
        if column.kind == "list":
            value = _as_list(value)
        elif isinstance(value, Decimal):
            value = float(value)
        elif value is not None and column.kind == "case":
            value = str(value)
        shaped[column.key] = value
    return shaped


def _as_list(value) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [str(value)]
    return [str(v) for v in parsed] if isinstance(parsed, list) else [str(parsed)]


def _csv_cell(value) -> str:
    """One cell as text. A value starting with = + - @ would be run as a formula by Excel, so it is
    defused with a leading quote (a cell someone typed, e.g. a supplier's message, must not execute)."""
    if value is None:
        return ""
    if isinstance(value, dict):  # a case: write its number (falling back to the id)
        value = value.get("number") or value.get("id")
    text = "; ".join(value) if isinstance(value, list) else str(value)
    return "'" + text if text.startswith(_FORMULA_STARTS) else text
