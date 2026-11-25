"""A small in-memory limit for public endpoints (no login to hang a limit on, so it is per caller address).

Each process keeps its own count, which is enough to stop someone trying many guessed links in a row.
"""

import threading
import time
from collections import defaultdict, deque


class RateLimit:
    def __init__(self, limit: int, window_seconds: float):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Count this call and say whether it is within the limit."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and moment - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(moment)
            if len(self._hits) > 5000:                       # never grow without bound
                for k in [k for k, v in self._hits.items() if not v or moment - v[-1] > self.window][:2500]:
                    self._hits.pop(k, None)
            return True
