from typing import Any

from pydantic import BaseModel


class ColumnInfo(BaseModel):
    key: str
    label: str
    kind: str


class DatasetSummary(BaseModel):
    key: str
    label: str
    description: str
    count: int


class DatasetGroup(BaseModel):
    label: str
    datasets: list[DatasetSummary]


class StoreRoomOverview(BaseModel):
    groups: list[DatasetGroup]


class DatasetPage(BaseModel):
    key: str
    label: str
    description: str
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
