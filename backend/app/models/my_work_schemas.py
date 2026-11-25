from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WorkItem(BaseModel):
    id: str
    title: str
    detail: str
    # An in-app path to open
    link: str
    action: str
    urgent: bool = False
    since: Optional[datetime] = None
    # When the admin will be told if nobody has acted (only for work the escalation rule covers, and only while it is on)
    escalates_at: Optional[datetime] = None
    note: Optional[str] = None


class HandledItem(BaseModel):
    id: str
    title: str
    what: str
    by: str
    at: datetime
    link: str


class WorkQueue(BaseModel):
    key: str
    title: str
    agent: str
    empty: str
    items: list[WorkItem]
    handled: list[HandledItem] = []


class MyWork(BaseModel):
    total: int
    queues: list[WorkQueue]
