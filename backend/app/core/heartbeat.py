"""Is the system's own background work still running?

The worker (follow-ups, escalation) and the instant mailbox watcher are loops inside the API process. If one of them
stops, nothing crashes and nobody is told: cases simply stop moving. Each loop records a beat every time it goes round;
`assess` turns "when did it last beat" into a plain verdict, and the monitor tells an admin when one goes quiet.

Pure where it can be: `assess` takes the clock and the beats as arguments, so it is easy to test.
"""

import threading
import time
from dataclasses import dataclass

STARTED = time.time()

# A tick can legitimately be slow (it may wait on the AI or the mail server), so be patient before shouting.
WORKER_WARN_AFTER_TICKS = 3     # quiet for this many intervals (plus a minute): warning
WORKER_DOWN_AFTER_TICKS = 10    # ... and this many: down
MAILBOX_GRACE_SECONDS = 180     # the watcher is renewed every ~9 minutes; this much slack on top
MAILBOX_DOWN_EXTRA_SECONDS = 600
MAILBOX_FAILS_WARN = 1
MAILBOX_FAILS_DOWN = 3
STARTUP_GRACE_SECONDS = 120     # right after a start nothing has had a chance to beat yet

WORKER = "worker"
MAILBOX = "mailbox"


@dataclass
class Beat:
    at: float                # when it last went round successfully (0 = never)
    failures: int = 0        # attempts in a row that failed
    last_error: str | None = None


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: str              # ok | warning | down
    detail: str


_lock = threading.Lock()
_beats: dict[str, Beat] = {}
_expected: set[str] = set()  # loops the app's startup said it is running (a test, or a disabled worker, expects none)


def expect(name: str) -> None:
    """Startup says this loop is meant to be running, so silence from it is a problem."""
    with _lock:
        _expected.add(name)


def expected() -> set[str]:
    with _lock:
        return set(_expected)


def beat(name: str, now: float | None = None) -> None:
    """The loop went round fine."""
    with _lock:
        _beats[name] = Beat(at=time.time() if now is None else now)


def fail(name: str, error: object) -> None:
    """The loop tried and it failed (the previous good beat is kept, so the age keeps counting)."""
    text = str(error).strip().splitlines()[0][:160] if str(error).strip() else type(error).__name__
    with _lock:
        previous = _beats.get(name, Beat(at=0))
        _beats[name] = Beat(at=previous.at, failures=previous.failures + 1, last_error=text)


def snapshot() -> dict[str, Beat]:
    with _lock:
        return {k: Beat(v.at, v.failures, v.last_error) for k, v in _beats.items()}


def reset() -> None:
    """For tests."""
    with _lock:
        _beats.clear()
        _expected.clear()


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f} h"


def assess(now: float, beats: dict[str, Beat], *, started: float, interval_seconds: float, expected: set[str],
           mailbox_idle_seconds: float = 540) -> list[Check]:
    """One verdict per background loop that is meant to be running."""
    checks: list[Check] = []
    starting = now - started < STARTUP_GRACE_SECONDS

    if WORKER in expected:
        b = beats.get(WORKER)
        if b is None or b.at == 0:
            checks.append(Check(WORKER, "Background worker", "ok" if starting else "down",
                                "Starting up" if starting else "It has not run since the app started. Follow-ups and escalation are not happening."))
        else:
            age = now - b.at
            warn = interval_seconds * WORKER_WARN_AFTER_TICKS + 60
            down = interval_seconds * WORKER_DOWN_AFTER_TICKS
            if age <= warn:
                checks.append(Check(WORKER, "Background worker", "ok", f"Last ran {_ago(age)} ago"))
            elif age <= down:
                checks.append(Check(WORKER, "Background worker", "warning", f"It has been quiet for {_ago(age)}. It may be stuck on a slow step."))
            else:
                checks.append(Check(WORKER, "Background worker", "down", f"It has not run for {_ago(age)}. Follow-ups and escalation are not happening."))

    if MAILBOX in expected:
        b = beats.get(MAILBOX)
        if b is None or b.at == 0:
            if starting:
                checks.append(Check(MAILBOX, "Instant mailbox watcher", "ok", "Starting up"))
            elif b is not None and b.failures:
                status = "down" if b.failures >= MAILBOX_FAILS_DOWN else "warning"
                checks.append(Check(MAILBOX, "Instant mailbox watcher", status, f"Cannot reach the mailbox ({b.failures} tries): {b.last_error}"))
            else:
                checks.append(Check(MAILBOX, "Instant mailbox watcher", "down", "It never connected. Supplier replies are only read once a minute, if at all."))
        else:
            age = now - b.at
            quiet_limit = mailbox_idle_seconds + MAILBOX_GRACE_SECONDS
            if b.failures >= MAILBOX_FAILS_DOWN:
                checks.append(Check(MAILBOX, "Instant mailbox watcher", "down", f"Cannot reach the mailbox ({b.failures} tries in a row): {b.last_error}"))
            elif b.failures >= MAILBOX_FAILS_WARN:
                checks.append(Check(MAILBOX, "Instant mailbox watcher", "warning", f"The last attempt to reach the mailbox failed: {b.last_error}"))
            elif age <= quiet_limit:
                checks.append(Check(MAILBOX, "Instant mailbox watcher", "ok", f"Watching the mailbox (checked in {_ago(age)} ago)"))
            elif age <= quiet_limit + MAILBOX_DOWN_EXTRA_SECONDS:
                checks.append(Check(MAILBOX, "Instant mailbox watcher", "warning", f"No sign of life for {_ago(age)}."))
            else:
                checks.append(Check(MAILBOX, "Instant mailbox watcher", "down", f"No sign of life for {_ago(age)}. Replies are only read at the next once-a-minute check."))
    return checks
