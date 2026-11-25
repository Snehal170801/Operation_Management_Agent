"""Who has a case open right now, so two people don't both act on it by mistake.

Each open page checks in every ~20 s; a check-in is forgotten after `TTL` seconds, so a closed tab or a lost connection
disappears by itself. Held in memory (it is only "who is looking right now", never worth saving). With several server
copies each would only know its own visitors; at this scale there is one.
"""

import threading
import time

TTL = 50.0
MAX_CASES = 5000

_lock = threading.Lock()
_seen: dict[str, dict[str, float]] = {}   # case id -> {username: last check-in}


def checkin(case_id: str, username: str, now: float | None = None) -> list[str]:
    """Record this person looking at the case, and return the OTHER people looking (names, sorted)."""
    now = time.time() if now is None else now
    case, me = str(case_id).lower(), username.strip().lower()
    with _lock:
        if len(_seen) >= MAX_CASES:
            _prune(now)
        viewers = _seen.setdefault(case, {})
        viewers[me] = now
        for name in [n for n, at in viewers.items() if now - at > TTL]:
            del viewers[name]
        return sorted(n for n in viewers if n != me)


def leave(case_id: str, username: str) -> None:
    with _lock:
        viewers = _seen.get(str(case_id).lower())
        if viewers:
            viewers.pop(username.strip().lower(), None)


def _prune(now: float) -> None:
    for case in [c for c, v in _seen.items() if all(now - at > TTL for at in v.values())]:
        del _seen[case]


def reset() -> None:
    with _lock:
        _seen.clear()
