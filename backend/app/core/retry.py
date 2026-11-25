"""Try again, briefly, when a failure is the kind that passes by itself (a dropped connection, a busy server).

Only failures the caller names are retried; anything else (a wrong password, a refused recipient, a bad request)
fails at once, because trying again cannot fix it and would only slow the person down or repeat a side effect.
"""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry(call: Callable[[], T], *, attempts: int = 3, delay: float = 0.3, backoff: float = 2.0,
          transient: Callable[[Exception], bool], what: str = "operation", sleep: Callable[[float], None] = time.sleep) -> T:
    """Run `call`; on a failure for which `transient(exc)` is true wait and try again, up to `attempts` in total.
    The last failure is raised unchanged, so callers keep handling the same exception types as before."""
    wait = delay
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if attempt == attempts or not transient(exc):
                raise
            logger.warning("%s failed (%s: %s); retrying in %.1fs (%d/%d)", what, type(exc).__name__, str(exc)[:120], wait, attempt, attempts - 1)
            sleep(wait)
            wait *= backoff
    raise AssertionError("unreachable")  # pragma: no cover
