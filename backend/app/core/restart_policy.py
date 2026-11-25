"""When may a background loop that has gone quiet be restarted by the app itself?

The watchdog (core/heartbeat.py, core/system_watch.py) says a loop is "down". Restarting it is the cure for the common case (a stuck or
crashed loop), but a loop that dies again at once must not be restarted forever, so the number of restarts per hour is limited and then a
person is told. Pure function: the clock and the history come in as arguments.
"""

CONFIRM_AFTER = 2          # evaluations in a row that say "down" before anything is done (one slow moment is not an outage)
WINDOW_SECONDS = 3600

RESTART = "restart"
GIVE_UP = "give_up"        # down, but the hourly limit is used up: a person must restart the server


def decide(now: float, down_streak: int, restarts: list[float], max_per_hour: int) -> tuple[str | None, list[float]]:
    """(action, restart times to remember). `restarts` are the clock times of earlier restarts of this loop. A limit of 0 switches
    automatic restarts off (the watchdog still tells the admins)."""
    recent = [t for t in restarts if now - t < WINDOW_SECONDS]
    if max_per_hour <= 0 or down_streak < CONFIRM_AFTER:
        return None, recent
    if len(recent) >= max_per_hour:
        return GIVE_UP, recent
    return RESTART, [*recent, now]
