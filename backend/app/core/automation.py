"""Controls on the automatic agents: the pause switch and the single-worker lock.

Pausing stops everything the system does on its own that reaches the outside world (quote
requests, purchase orders, chasing vendors, reading the mailbox). People can still use the app,
and cases that were held are caught up automatically after resume.
"""

import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.repositories import automation_repository

_PAUSED_KEY = "automation_paused"
_WORKER_LEASE = "background-worker"

# Unique per running process, so two instances never mistake each other's lease for their own.
INSTANCE_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


@dataclass(frozen=True)
class AutomationState:
    paused: bool
    updated_at: Optional[datetime]
    updated_by: Optional[str]


def get_state() -> AutomationState:
    row = automation_repository.get_setting(_PAUSED_KEY)
    if row is None:
        return AutomationState(False, None, None)
    return AutomationState(row.setting_value == "1", row.updated_at, row.updated_by)


def is_paused() -> bool:
    return get_state().paused


def set_paused(paused: bool, by: str | None) -> AutomationState:
    automation_repository.set_setting(_PAUSED_KEY, "1" if paused else "0", by)
    return get_state()


def acquire_worker_lease(ttl_seconds: int) -> bool:
    return automation_repository.try_acquire_lease(_WORKER_LEASE, INSTANCE_ID, ttl_seconds)
