"""The supervisor restarts a background loop the watchdog calls "down", within an hourly limit, and tells the admins once per episode."""

import asyncio

import pytest

from app.core import heartbeat, restart_policy as rp
from app.core.config import settings
from app.core.heartbeat import Check
from app.orchestrator import supervisor as sup

NOW = 100_000.0


# ---- the rule ---------------------------------------------------------------------------------------------------------------------------

def test_nothing_is_done_until_down_has_been_seen_twice_in_a_row():
    assert rp.decide(NOW, 1, [], 3) == (None, [])
    assert rp.decide(NOW, 2, [], 3) == (rp.RESTART, [NOW])


def test_restarts_are_limited_per_hour_and_old_ones_stop_counting():
    assert rp.decide(NOW, 5, [NOW - 100, NOW - 200, NOW - 300], 3) == (rp.GIVE_UP, [NOW - 100, NOW - 200, NOW - 300])
    action, kept = rp.decide(NOW, 5, [NOW - 4000, NOW - 200, NOW - 300], 3)
    assert action == rp.RESTART and kept == [NOW - 200, NOW - 300, NOW]                  # the 4000-second-old one has aged out


def test_a_limit_of_zero_means_never_restart():
    assert rp.decide(NOW, 99, [], 0)[0] is None


# ---- the supervisor ---------------------------------------------------------------------------------------------------------------------

def down(name=heartbeat.WORKER):
    return Check(name, "Background worker", "down", "It has not run for 12 min.")


def ok(name=heartbeat.WORKER):
    return Check(name, "Background worker", "ok", "Last ran 5 s ago")


@pytest.fixture
def world(monkeypatch):
    told, recorded, started = [], [], []
    monkeypatch.setattr(sup.notification_agent, "notify_system", lambda kind, label, detail, since: told.append(kind) or 1)
    monkeypatch.setattr(sup.audit, "record", lambda action, **k: recorded.append((action, k["target_id"])))
    monkeypatch.setattr(settings, "LOOP_RESTARTS_PER_HOUR", 3)
    heartbeat.reset()

    async def forever():
        started.append(1)
        await asyncio.sleep(3600)
    return told, recorded, started, forever


def run(coro):
    return asyncio.run(coro)


def test_a_down_loop_is_cancelled_and_started_again_and_the_admins_told_once(world):
    told, recorded, started, forever = world

    async def go():
        s = sup.Supervisor({heartbeat.WORKER: forever})
        s.start()
        await asyncio.sleep(0)
        first = s.loops[heartbeat.WORKER].task
        assert await s.step([down()], NOW) == []                                  # once is not enough
        assert await s.step([down()], NOW + 60) == [(heartbeat.WORKER, "restarted")]
        await asyncio.sleep(0)
        assert first.cancelled() and s.loops[heartbeat.WORKER].task is not first and len(started) == 2
        s.stop()
    run(go())
    assert told == ["restarted"] and recorded == [("system.loop_restarted", heartbeat.WORKER)]


def test_a_loop_that_keeps_dying_is_restarted_up_to_the_limit_then_a_person_is_told_once(world):
    told, recorded, started, forever = world

    async def go():
        s = sup.Supervisor({heartbeat.WORKER: forever})
        s.start()
        outcomes = [await s.step([down()], NOW + 60 * n) for n in range(8)]
        s.stop()
        return outcomes
    outcomes = run(go())
    flat = [o for step in outcomes for o in step]
    assert flat == [(heartbeat.WORKER, "restarted")] * 3 + [(heartbeat.WORKER, "gave_up")]           # three restarts, then one give-up, then silence
    assert told == ["restarted", "gave_up"] and len(recorded) == 3                                    # one email for the episode's restarts, one for giving up


def test_a_healthy_loop_ends_the_episode_so_the_next_one_is_announced_again(world):
    told, recorded, started, forever = world

    async def go():
        s = sup.Supervisor({heartbeat.WORKER: forever})
        s.start()
        await s.step([down()], NOW)
        await s.step([down()], NOW + 60)
        await s.step([ok()], NOW + 120)
        await s.step([down()], NOW + 180)
        await s.step([down()], NOW + 240)
        s.stop()
    run(go())
    assert told == ["restarted", "restarted"]


def test_a_warning_or_a_loop_that_is_not_supervised_is_left_alone(world):
    told, recorded, started, forever = world

    async def go():
        s = sup.Supervisor({heartbeat.WORKER: forever})
        s.start()
        await asyncio.sleep(0)
        warn = Check(heartbeat.WORKER, "Background worker", "warning", "quiet")
        for n in range(5):
            assert await s.step([warn, down("something-else")], NOW + n) == []
        s.stop()
    run(go())
    assert told == [] and len(started) == 1


def test_a_failure_while_restarting_or_telling_never_stops_the_supervisor(world, monkeypatch):
    told, recorded, started, forever = world
    monkeypatch.setattr(sup.notification_agent, "notify_system", lambda *a: (_ for _ in ()).throw(RuntimeError("smtp down")))
    monkeypatch.setattr(sup.audit, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))

    async def go():
        s = sup.Supervisor({heartbeat.WORKER: forever})
        s.start()
        await asyncio.sleep(0)
        await s.step([down()], NOW)
        result = await s.step([down()], NOW + 60)
        await asyncio.sleep(0.05)
        s.stop()
        return result
    assert run(go()) == [(heartbeat.WORKER, "restarted")] and len(started) == 2


def test_switched_off_the_supervisor_only_watches(world, monkeypatch):
    told, recorded, started, forever = world
    monkeypatch.setattr(settings, "LOOP_RESTARTS_PER_HOUR", 0)

    async def go():
        s = sup.Supervisor({heartbeat.WORKER: forever})
        s.start()
        await asyncio.sleep(0)
        for n in range(4):
            assert await s.step([down()], NOW + n) == []
        s.stop()
    run(go())
    assert told == [] and len(started) == 1


def test_a_stuck_loop_that_ignores_cancel_is_still_replaced(world):
    told, recorded, started, forever = world

    refusals = []

    async def stubborn():
        started.append(1)
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                refusals.append(1)
                if len(refusals) > 2:
                    raise                                                     # refuses the first cancels (as a thread stuck in a slow step would), then gives in

    async def go():
        s = sup.Supervisor({heartbeat.WORKER: stubborn})
        s.start()
        await asyncio.sleep(0)
        await s.step([down()], NOW)
        await s.step([down()], NOW + 60)
        await asyncio.sleep(0)
        count = len(started)
        for loop in s.loops.values():
            loop.task.cancel()
            loop.task.cancel()
        await asyncio.sleep(0.2)
        return count
    sup_wait = sup.asyncio.wait_for

    async def quick(awaitable, timeout):
        return await sup_wait(awaitable, 0.05)
    sup.asyncio.wait_for = quick
    try:
        assert run(go()) == 2
    finally:
        sup.asyncio.wait_for = sup_wait


def test_the_setting_is_in_configure_with_a_sane_range():
    from app.core import tunables
    t = {x.key: x for x in tunables.CATALOG}["LOOP_RESTARTS_PER_HOUR"]
    assert t.group == "worker" and tunables.validate({"LOOP_RESTARTS_PER_HOUR": 0}) == {"LOOP_RESTARTS_PER_HOUR": 0}
    with pytest.raises(tunables.InvalidSetting):
        tunables.validate({"LOOP_RESTARTS_PER_HOUR": 99})


def test_the_app_starts_the_loops_through_the_supervisor_and_stops_them_on_shutdown(monkeypatch):
    import app.main as main
    started, stopped = [], []

    def fake(name):
        async def loop():
            started.append(name)
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                stopped.append(name)
                raise
        return loop
    monkeypatch.setattr(settings, "WORKER_ENABLED", True)
    monkeypatch.setattr(settings, "IMAP_HOST", "")
    monkeypatch.setattr(main.access, "sync_system_roles", lambda: None)
    monkeypatch.setattr(main.tunables, "refresh", lambda: None)
    for name in ("run_forever", "watch_mailbox_forever", "watch_health_forever"):
        monkeypatch.setattr(main.worker, name, fake(name))
    heartbeat.reset()

    async def go():
        async with main.lifespan(main.app):
            await asyncio.sleep(0.05)
            assert sorted(started) == ["run_forever", "watch_health_forever", "watch_mailbox_forever"]
        await asyncio.sleep(0.05)
    run(go())
    assert sorted(stopped) == ["run_forever", "watch_health_forever", "watch_mailbox_forever"]
    heartbeat.reset()
