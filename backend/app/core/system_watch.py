"""Turns "a background loop went quiet" into "an admin was told", exactly once per problem.

The monitor evaluates the checks from `heartbeat.assess` every minute. A problem must show up twice in a row before
anyone is told (a single slow moment is not an outage), the admin is told once, and told again when it recovers.
This class holds only the remembering; sending the email and the clock belong to the caller.
"""

import time
from dataclasses import dataclass
from threading import Lock

from app.core import heartbeat
from app.core.config import settings
from app.core.heartbeat import Check

CONFIRM_AFTER = 2  # evaluations in a row before a problem is announced


@dataclass(frozen=True)
class Event:
    kind: str            # "down" (a problem to announce) | "recovered"
    check: Check
    since: float         # when it first looked wrong


class Watch:
    def __init__(self) -> None:
        self._lock = Lock()
        self._streak: dict[str, int] = {}
        self._since: dict[str, float] = {}
        self._announced: set[str] = set()

    def step(self, checks: list[Check], now: float) -> list[Event]:
        events: list[Event] = []
        with self._lock:
            for c in checks:
                if c.status == "ok":
                    if c.key in self._announced:
                        events.append(Event("recovered", c, self._since.get(c.key, now)))
                        self._announced.discard(c.key)
                    self._streak.pop(c.key, None)
                    self._since.pop(c.key, None)
                    continue
                self._since.setdefault(c.key, now)
                self._streak[c.key] = self._streak.get(c.key, 0) + 1
                if self._streak[c.key] >= CONFIRM_AFTER and c.key not in self._announced:
                    self._announced.add(c.key)
                    events.append(Event("down", c, self._since[c.key]))
        return events

    def since(self, key: str, fallback: float) -> float:
        with self._lock:
            return self._since.get(key, fallback)

    def reset(self) -> None:
        with self._lock:
            self._streak.clear()
            self._since.clear()
            self._announced.clear()


watch = Watch()


def current_checks(now: float | None = None) -> list[Check]:
    """The verdict on each background loop that is meant to be running (shown on System Health, the bell, and emailed)."""
    return heartbeat.assess(
        time.time() if now is None else now, heartbeat.snapshot(), started=heartbeat.STARTED,
        interval_seconds=settings.WORKER_INTERVAL_SECONDS, expected=heartbeat.expected(),
    )
