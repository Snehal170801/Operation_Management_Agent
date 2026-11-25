import asyncio
import json

from fastapi.testclient import TestClient

from app.api.routes import live
from app.core.live import LiveHub
from app.main import app

client = TestClient(app)


async def drain(sub, n):
    return [json.loads(await asyncio.wait_for(sub.queue.get(), 1)) for _ in range(n)]


def make_hub(owners):
    hub = LiveHub()
    hub._owner_of = lambda case_id: owners.get(str(case_id).lower())   # no database in these tests
    return hub


def test_staff_hear_about_every_case_and_a_requester_only_their_own():
    async def go():
        hub = make_hub({"c1": "alice@x.co", "c2": "bob@x.co"})
        hub.attach(asyncio.get_running_loop())
        staff, alice = hub.subscribe("mgr@x.co", True), hub.subscribe("Alice@x.co", False)
        hub.publish("c1", "step.started")
        hub.publish("c2", "stage.po_issued")
        await asyncio.sleep(0.05)
        return (await drain(staff, 2)), (await drain(alice, 1)), alice.queue.empty()
    staff_got, alice_got, alice_done = asyncio.run(go())
    assert [m["id"] for m in staff_got] == ["c1", "c2"]
    assert [m["id"] for m in alice_got] == ["c1"] and alice_done
    assert staff_got[0] == {"t": "case", "id": "c1", "e": "step.started"}


def test_a_signal_says_which_case_changed_and_nothing_about_its_content():
    async def go():
        hub = make_hub({"c1": "alice@x.co"})
        hub.attach(asyncio.get_running_loop())
        sub = hub.subscribe("alice@x.co", False)
        hub.publish("c1", "vendor.selected")
        await asyncio.sleep(0.05)
        return await drain(sub, 1)
    assert set(asyncio.run(go())[0]) == {"t", "id", "e"}


def test_publishing_from_another_thread_reaches_the_page():
    import threading

    async def go():
        hub = make_hub({})
        hub.attach(asyncio.get_running_loop())
        sub = hub.subscribe("mgr@x.co", True)
        threading.Thread(target=hub.publish, args=("c9", "case.closed")).start()
        return await drain(sub, 1)
    assert asyncio.run(go())[0]["id"] == "c9"


def test_publishing_with_nobody_listening_or_a_broken_hub_never_raises():
    LiveHub().publish("c1", "x")
    hub = LiveHub()
    hub.attach(asyncio.new_event_loop())      # a loop that is not running
    hub.subscribe("a", True)
    hub.publish("c1", "x")


def test_a_page_that_stops_reading_cannot_grow_the_queue_without_limit():
    async def go():
        hub = make_hub({})
        hub.attach(asyncio.get_running_loop())
        sub = hub.subscribe("mgr@x.co", True)
        for i in range(500):
            hub.publish(f"c{i}", "x")
        await asyncio.sleep(0.1)
        return sub.queue.qsize()
    assert asyncio.run(go()) == 200


def test_the_stream_greets_pings_when_quiet_ends_on_time_and_lets_go_of_the_subscriber():
    async def go():
        hub = make_hub({})
        live.hub = hub
        sub = hub.subscribe("mgr@x.co", True)
        chunks = [c async for c in live.event_stream(sub, heartbeat=0.05, lifetime=0.2)]
        return chunks, hub.listeners
    chunks, listeners = asyncio.run(go())
    assert chunks[0] == "retry: 3000\n\n" and "hello" in chunks[1]
    assert ": ping\n\n" in chunks and listeners == 0


def test_the_stream_passes_a_signal_on():
    async def go():
        hub = make_hub({})
        live.hub = hub
        hub.attach(asyncio.get_running_loop())
        sub = hub.subscribe("mgr@x.co", True)
        hub.publish("c1", "po.issued")
        return [c async for c in live.event_stream(sub, heartbeat=0.05, lifetime=0.25)]
    assert any('"id": "c1"' in c for c in asyncio.run(go()))


def test_the_stream_needs_a_login():
    assert client.get("/live/stream").status_code == 401
