from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import agent_flow_controller
from app.core import access, security
from app.core.agent_flow import REPLAY_MAX_FRAMES, build_flow, build_replay
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.orchestrator import case_pipeline
from app.repositories import role_repository, user_repository

from .fake_world import World, standard_world
from .test_agent_flow import NOW, Log, live

client = TestClient(app)
CASE = {"case_id": "C1"}


def replay(log, audience="staff"):
    return build_replay(CASE, log.events, audience)


def states(frame):
    return [a["state"] for a in frame["agents"]]


def test_a_case_with_no_events_has_no_frames():
    assert replay(Log())["frames"] == []


def test_each_visible_moment_is_a_frame_in_order_and_agents_progress_through_them():
    log = (Log().add("case.created", {}, 30)
           .start("read_request", "a", ago=29).finish("read_request", "a", ago=27).add("stage.purchase_request_created", {}, 27)
           .start("check_stock", "b", ago=26).finish("check_stock", "b", ago=25).add("stage.sourcing_needed", {}, 25))
    frames = replay(log)["frames"]
    assert [f["event"]["text"] for f in frames] == [
        "Reading your request", "Finished: reading your request (2.0 s)", "Checking stock", "Finished: checking stock (2.0 s)"]
    assert states(frames[0])[0] == "working"
    assert states(frames[1])[:2] == ["done", "pending"]
    assert [f["at"] for f in frames] == sorted(f["at"] for f in frames)


def test_the_stage_written_after_an_event_is_applied_to_that_moments_picture():
    log = Log().start("check_stock", "b", ago=9).finish("check_stock", "b", ago=8).add("stage.sourcing_needed", {}, 8)
    last = replay(log)["frames"][-1]
    assert states(last)[1] == "done"          # procurement is done, so the stage after it had to be applied


def test_enough_stock_replays_to_a_fulfilled_outcome():
    log = (Log().start("read_request", "a", ago=9).finish("read_request", "a", ago=8).add("stage.purchase_request_created", {}, 8)
           .start("check_stock", "b", ago=7).finish("check_stock", "b", ago=6)
           .add("case.closed", {"stage": "fulfilled_from_stock", "reason": "x"}, 6))
    last = replay(log)["frames"][-1]
    assert last["outcome"] == "fulfilled" and states(last)[2:] == ["skipped"] * 5


def test_a_long_story_is_thinned_but_keeps_the_ending():
    log = Log()
    for n in range(REPLAY_MAX_FRAMES + 60):
        log.start("read_quote", f"r{n}", ago=1000 - n)
    frames = replay(log)["frames"]
    assert len(frames) == REPLAY_MAX_FRAMES
    assert frames[-1]["event"]["id"] == max(e["event_id"] for e in log.events)


def test_a_requester_replay_has_no_internal_detail():
    log = (Log().start("check_stock", "a", detail="SECRET DETAIL", ago=5).progress("check_stock", 1, 2, "SECRET ITEM", "a", ago=4)
           .fail("check_stock", "a", error="SECRET ERROR", ago=3))
    assert "SECRET" not in str(replay(log, "requester"))
    assert "SECRET ERROR" in str(replay(log, "staff"))


@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def real_events(w, case_id):
    return [{"event_id": e.event_id, "event_type": e.event_type, "agent_name": e.agent_name, "payload": e.payload,
             "created_at": e.created_at} for e in w.events[case_id]]


def test_the_last_frame_of_a_real_replay_matches_the_live_page(w):
    case_id = w.submit("50 cameras")
    for v, t in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30", "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, v, t)
    w.expire_quote_deadline(case_id)
    w.tick()
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    w.reply(case_id, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")

    result = build_replay({"case_id": case_id}, real_events(w, case_id), "staff")
    final, now_state = result["frames"][-1], live(w, case_id)
    assert [(a["key"], a["state"]) for a in final["agents"]] == [(a["key"], a["state"]) for a in now_state["agents"]]
    assert final["outcome"] == "completed" and states(final) == ["done"] * 7
    # and it really did pass through the interesting states on the way
    seen = {s for f in result["frames"] for s in states(f)}
    assert {"working", "waiting", "done", "pending"} <= seen


def test_replaying_an_old_case_with_no_step_signals_still_works(w):
    case_id = w.submit("10 laptops")
    w.events[case_id] = [e for e in w.events[case_id] if not e.event_type.startswith("step.")]
    frames = build_replay({"case_id": case_id}, real_events(w, case_id), "staff")["frames"]
    assert frames == [] or frames[-1]["outcome"] == "fulfilled"


@pytest.fixture
def people(monkeypatch):
    users = {"alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
             "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True)}
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    mine, theirs = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"
    owners = {mine: "alice@x.co", theirs: "bob@x.co"}
    monkeypatch.setattr("app.core.case_access.case_repository.find_case_by_id",
                        lambda cid: SimpleNamespace(requester_id=owners[cid]) if cid in owners else None)
    ops = agent_flow_controller.operations_agent
    monkeypatch.setattr(ops, "get_case_status", lambda cid: {"case_id": cid, "requester_id": "alice@x.co", "stage": "created", "status": "open"})
    from app.core.exceptions import PurchaseOrderNotFound as _NoOrder

    def _no_order(cid):
        raise _NoOrder(cid)
    monkeypatch.setattr(agent_flow_controller.delivery_agent, "get_delivery", _no_order)
    monkeypatch.setattr(agent_flow_controller.purchase_agent, "get_purchase_request", lambda cid: {
        "raw_request": "We need 50 CCTV cameras for Pune", "cost_center": "OPS-7", "created_at": NOW,
        "items": [{"description": "CCTV camera", "quantity": 50}]})
    monkeypatch.setattr(ops, "get_case_events", lambda cid: Log().start("read_request", detail="SECRET").events)
    access.invalidate()
    yield mine, theirs
    access.invalidate()


def as_(uid, role):
    t, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {t}"}


def test_replay_needs_a_login():
    assert client.get("/agent-flow/cases/x/replay").status_code == 401


def test_a_requester_cannot_replay_someone_elses_case(people):
    _, theirs = people
    assert client.get(f"/agent-flow/cases/{theirs}/replay", headers=as_("alice", "user")).status_code == 404


def test_a_requester_can_replay_their_own_without_detail_and_staff_get_it(people):
    mine, _ = people
    own = client.get(f"/agent-flow/cases/{mine}/replay", headers=as_("alice", "user"))
    assert own.status_code == 200 and own.json()["audience"] == "requester" and "SECRET" not in own.text
    staff = client.get(f"/agent-flow/cases/{mine}/replay", headers=as_("mgr", "manager")).json()
    assert staff["audience"] == "staff" and "SECRET" in str(staff)


def test_the_replay_carries_the_request_too(people):
    mine, _ = people
    own = client.get(f"/agent-flow/cases/{mine}/replay", headers=as_("alice", "user")).json()["request"]
    assert own["raw_text"] == "We need 50 CCTV cameras for Pune" and own["requested_by"] is None
    assert client.get(f"/agent-flow/cases/{mine}/replay", headers=as_("mgr", "manager")).json()["request"]["requested_by"] == "alice@x.co"
