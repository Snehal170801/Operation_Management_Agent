"""Push "something changed" to the pages people have open, the moment it happens.

A signal carries only which case changed and what kind of event it was. The page reacts by re-reading what it is
showing through the normal, permission-checked endpoints, so this channel can never leak a price, a supplier
or a reason. Who gets which signal is still limited: staff hear about every case, a requester only their own.

Events are written from many threads (the worker, request handlers); each open page is served by the web
server's event loop. `publish` is safe to call from any thread and never raises or blocks the caller.
"""

import asyncio
import json
import logging
import threading

logger = logging.getLogger(__name__)

QUEUE_SIZE = 200          # a page that falls this far behind just misses signals; it re-reads on the next one
OWNER_CACHE_MAX = 2000


class Subscriber:
    """One open page."""

    def __init__(self, username: str, sees_all: bool):
        self.username = username.strip().lower()
        self.sees_all = sees_all
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)


class LiveHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owners: dict[str, str] = {}

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once at startup with the web server's event loop."""
        self._loop = loop

    def subscribe(self, username: str, sees_all: bool) -> Subscriber:
        sub = Subscriber(username, sees_all)
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs.discard(sub)

    @property
    def listeners(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, case_id: str, event_type: str) -> None:
        try:
            with self._lock:
                subs, loop = list(self._subs), self._loop
            if not subs or loop is None:
                return
            owner = self._owner_of(case_id) if any(not s.sees_all for s in subs) else None
            message = json.dumps({"t": "case", "id": str(case_id).lower(), "e": event_type})
            for sub in subs:
                if sub.sees_all or (owner is not None and owner == sub.username):
                    loop.call_soon_threadsafe(self._offer, sub, message)
        except Exception:  # a failed signal must never break the work that caused it
            logger.warning("could not publish a live signal", exc_info=True)

    @staticmethod
    def _offer(sub: Subscriber, message: str) -> None:
        try:
            sub.queue.put_nowait(message)
        except asyncio.QueueFull:
            pass

    def _owner_of(self, case_id: str) -> str | None:
        key = str(case_id).lower()
        owner = self._owners.get(key)
        if owner is None:
            from app.repositories import case_repository  # local import: the repository publishes through this module

            row = case_repository.find_case_by_id(case_id)
            if row is None:
                return None
            owner = row.requester_id.strip().lower()
            if len(self._owners) >= OWNER_CACHE_MAX:
                self._owners.clear()
            self._owners[key] = owner
        return owner


hub = LiveHub()
