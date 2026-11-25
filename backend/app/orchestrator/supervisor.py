"""Keeps the background loops alive. The watchdog only TELLS people a loop went quiet; this restarts it.

Owned by app/main.py (not by the loops themselves: a stuck loop cannot restart itself). Every minute it reads the same verdicts the
watchdog uses (core/heartbeat.assess); a loop that is "down" twice in a row is cancelled and started again from its factory, at most
`LOOP_RESTARTS_PER_HOUR` times an hour. Admins are told once per episode (the first restart, and again only if the limit is used up);
the episode ends when the loop is healthy again. A thread already inside a slow step cannot be killed, only the loop around it is
replaced, so a loop that is stuck for good will hit the limit and ask a person to restart the server.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.agents import notification_agent
from app.core import audit, heartbeat, restart_policy, system_watch
from app.core.config import settings

logger = logging.getLogger(__name__)
CHECK_SECONDS = 60


@dataclass
class _Loop:
    factory: Callable[[], Awaitable]
    task: "asyncio.Task | None" = None
    down_streak: int = 0
    restarts: list[float] = field(default_factory=list)
    told_restart: bool = False
    told_give_up: bool = False


class Supervisor:
    def __init__(self, factories: dict[str, Callable[[], Awaitable]]):
        self.loops = {name: _Loop(factory) for name, factory in factories.items()}

    def start(self) -> None:
        for loop in self.loops.values():
            loop.task = asyncio.create_task(loop.factory())

    def stop(self) -> None:
        for loop in self.loops.values():
            if loop.task:
                loop.task.cancel()

    def tasks(self) -> list[asyncio.Task]:
        return [loop.task for loop in self.loops.values() if loop.task]

    async def step(self, checks: list[heartbeat.Check], now: float) -> list[tuple[str, str]]:
        """One look at the verdicts. Returns [(loop name, "restarted" | "gave_up")] for what was done. Never raises."""
        done: list[tuple[str, str]] = []
        status = {c.key: c for c in checks}
        for name, loop in self.loops.items():
            check = status.get(name)
            if check is None or check.status != "down":
                if check is not None and check.status == "ok":
                    loop.down_streak = 0
                    loop.told_restart = loop.told_give_up = False         # healthy again: the episode is over
                elif check is not None:
                    loop.down_streak = 0                                  # "warning" is not down
                continue
            loop.down_streak += 1
            action, loop.restarts = restart_policy.decide(now, loop.down_streak, loop.restarts, settings.LOOP_RESTARTS_PER_HOUR)
            try:
                if action == restart_policy.RESTART:
                    await self._restart(name, loop, check)
                    done.append((name, "restarted"))
                elif action == restart_policy.GIVE_UP and not loop.told_give_up:
                    loop.told_give_up = True
                    await asyncio.to_thread(self._tell, name, check, "gave_up")
                    done.append((name, "gave_up"))
            except Exception:
                logger.exception("Could not recover the %s loop", name)
        return done

    async def _restart(self, name: str, loop: _Loop, check: heartbeat.Check) -> None:
        if loop.task is not None:
            loop.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(loop.task), 5)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass                                                      # a loop stuck inside a thread does not stop quickly: replace it anyway
        loop.task = asyncio.create_task(loop.factory())
        heartbeat.beat(name)                                              # a fresh start: judged from now, not from the old silence
        logger.warning("Restarted the %s loop (%s)", name, check.detail)
        await asyncio.to_thread(self._record_and_tell, name, check, loop)

    def _record_and_tell(self, name: str, check: heartbeat.Check, loop: _Loop) -> None:
        try:
            audit.record("system.loop_restarted", actor_username="supervisor", target_type="system", target_id=name, detail={"why": check.detail})
        except Exception:
            logger.exception("Could not record the restart of %s", name)
        if not loop.told_restart:
            loop.told_restart = True
            self._tell(name, check, "restarted")

    @staticmethod
    def _tell(name: str, check: heartbeat.Check, kind: str) -> None:
        try:
            since = time.strftime("%d %b %H:%M", time.localtime(system_watch.watch.since(name, time.time())))
            notification_agent.notify_system(kind, check.label, check.detail, since)
        except Exception:
            logger.exception("Could not tell the admins about the %s of %s", kind, name)


async def supervise_forever(supervisor: Supervisor) -> None:
    logger.info("Loop supervisor started (every %ss, up to %s restarts an hour)", CHECK_SECONDS, settings.LOOP_RESTARTS_PER_HOUR)
    while True:
        try:
            await supervisor.step(system_watch.current_checks(), time.time())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Loop supervisor failed")
        await asyncio.sleep(CHECK_SECONDS)
