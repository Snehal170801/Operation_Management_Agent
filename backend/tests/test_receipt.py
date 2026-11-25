"""The requester's own "did the goods reach you?" check: a second check beside Receiving's, never a blocker."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents import delivery_agent, notification_agent, operations_agent
from app.controllers import receipt_controller
from app.core import access, receipt, security
from app.core.my_work import build_my_work
from app.core.permissions import ALL_PERMISSIONS, DEPARTMENTS
from app.main import app
from app.repositories import role_repository, user_repository

client = TestClient(app)
T0 = datetime(2026, 3, 2, 9)


def ev(kind, minutes, **payload):
    return {"event_type": kind, "payload": payload, "created_at": T0 + timedelta(minutes=minutes)}


# ---- the pure rules ----

def test_nothing_to_ask_until_receiving_has_confirmed():
    assert receipt.receipt_state(False, [])["state"] == "not_delivered"
    assert receipt.receipt_state(False, [ev(receipt.CONFIRMED, 1)])["state"] == "not_delivered"


def test_states_follow_the_latest_answer():
    assert receipt.receipt_state(True, [])["state"] == "ask"
    assert receipt.receipt_state(True, [ev(receipt.CONFIRMED, 1)])["state"] == "confirmed"
    assert receipt.receipt_state(True, [ev(receipt.DISPUTED, 1, note="box was empty")]) == {"state": "disputed", "note": "box was empty", "at": T0 + timedelta(minutes=1)}
    assert receipt.receipt_state(True, [ev(receipt.DISPUTED, 1), ev(receipt.HANDLED, 2)])["state"] == "followed_up"
    # after a follow-up they can say yes (or no again) and that is what counts
    assert receipt.receipt_state(True, [ev(receipt.DISPUTED, 1), ev(receipt.HANDLED, 2), ev(receipt.CONFIRMED, 3)])["state"] == "confirmed"
    assert receipt.receipt_state(True, [ev(receipt.CONFIRMED, 1), ev(receipt.DISPUTED, 2)])["state"] == "disputed"
    # events in any order, and unrelated events ignored
    assert receipt.receipt_state(True, [ev(receipt.CONFIRMED, 5), ev("stage.delivered", 9), ev(receipt.DISPUTED, 1)])["state"] == "confirmed"


def test_open_disputes_only_where_the_latest_word_is_no():
    rows = [
        {"case_id": "A", "event_type": receipt.DISPUTED, "payload": {"by": "ann", "note": "wrong colour"}, "created_at": T0},
        {"case_id": "B", "event_type": receipt.DISPUTED, "payload": {"by": "bob"}, "created_at": T0},
        {"case_id": "B", "event_type": receipt.HANDLED, "payload": {}, "created_at": T0 + timedelta(hours=1)},
        {"case_id": "C", "event_type": receipt.DISPUTED, "payload": {"by": "cy"}, "created_at": T0},
        {"case_id": "C", "event_type": receipt.CONFIRMED, "payload": {}, "created_at": T0 + timedelta(hours=1)},
    ]
    found = receipt.open_disputes(rows)
    assert list(found) == ["a"] and found["a"]["note"] == "wrong colour" and found["a"]["by"] == "ann"


def test_notes_are_trimmed_and_capped():
    assert receipt.clean_note("  hi  ") == "hi" and receipt.clean_note("   ") is None and receipt.clean_note(None) is None
    assert len(receipt.clean_note("x" * 900)) == receipt.NOTE_MAX


def test_a_dispute_shows_in_receivings_my_work_as_urgent():
    cases = [{"case_id": "AAA", "case_number": "REQ-1", "items_summary": "8 racks", "status": "open", "stage": "delivered", "requester_id": "ann"}]
    work = build_my_work("recv", lambda p: p == "delivery:confirm", approvals=[], cases=cases, deliveries=[], invoices=[], stock=[], now=T0,
                         disputes={"aaa": {"note": "box empty", "since": T0, "by": "ann"}})
    item = work["queues"][0]["items"][0]
    assert item["urgent"] and "ann says the goods have NOT reached them" in item["detail"] and "box empty" in item["detail"]
    assert item["link"] == "/cases/aaa" and work["total"] == 1


# ---- the routes ----

@pytest.fixture
def world(monkeypatch):
    users = {u: SimpleNamespace(user_id=u, username=u, role=r, is_active=True, email=None, display_name=u)
             for u, r in (("ann", "user"), ("bob", "user"), ("recv", "dept_delivery"))}
    roles = {f"dept_{d.key}": set(d.permissions) for d in DEPARTMENTS}
    roles.update({"admin": set(ALL_PERMISSIONS), "user": {"cases:read", "cases:create"}})
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: roles)
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(str(uid).lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    monkeypatch.setattr(receipt_controller.audit, "record", lambda *a, **k: None)
    state = SimpleNamespace(delivered=True, events=[], alerts=[], clock=0)
    monkeypatch.setattr(operations_agent, "get_case_status", lambda cid: {"case_id": cid, "case_number": "REQ-9", "requester_id": "ann"})
    monkeypatch.setattr(delivery_agent, "get_delivery", lambda cid: {"delivery_status": "delivered" if state.delivered else "pending"})
    monkeypatch.setattr(operations_agent, "get_case_events", lambda cid: list(state.events))

    def publish(cid, kind, agent_name=None, payload=None):
        state.clock += 1
        state.events.append({"event_type": kind, "payload": payload or {}, "created_at": T0 + timedelta(minutes=state.clock)})
    monkeypatch.setattr(operations_agent, "publish_event", publish)
    monkeypatch.setattr(notification_agent, "notify_case_stalled", lambda cid, reason, team=None: state.alerts.append((team, reason)))
    access.invalidate()
    return state


def head(uid):
    return {"Authorization": f"Bearer {security.create_access_token(uid, uid, 'x')[0]}"}


def test_requester_is_asked_then_confirms(world):
    assert client.get("/cases/c1/receipt", headers=head("ann")).json()["state"] == "ask"
    r = client.post("/cases/c1/receipt", json={"received": True}, headers=head("ann"))
    assert r.status_code == 200 and r.json()["state"] == "confirmed" and world.alerts == []


def test_saying_no_alerts_receiving_with_their_words(world):
    r = client.post("/cases/c1/receipt", json={"received": False, "note": "Only 6 of 8 arrived"}, headers=head("ann"))
    assert r.json()["state"] == "disputed" and r.json()["note"] == "Only 6 of 8 arrived"
    assert len(world.alerts) == 1 and world.alerts[0][0] == "delivery" and "Only 6 of 8 arrived" in world.alerts[0][1]


def test_receiving_follows_up_and_the_requester_is_asked_again(world):
    client.post("/cases/c1/receipt", json={"received": False}, headers=head("ann"))
    assert client.post("/cases/c1/delivery/dispute-handled", json={"note": "rang the courier"}, headers=head("recv")).status_code == 204
    assert client.get("/cases/c1/receipt", headers=head("ann")).json()["state"] == "followed_up"
    assert client.post("/cases/c1/receipt", json={"received": True}, headers=head("ann")).json()["state"] == "confirmed"


def test_cannot_confirm_before_receiving_has(world):
    world.delivered = False
    assert client.get("/cases/c1/receipt", headers=head("ann")).json()["state"] == "not_delivered"
    assert client.post("/cases/c1/receipt", json={"received": True}, headers=head("ann")).status_code == 422
    assert world.events == []


def test_only_the_requester_who_asked_can_answer(world):
    assert client.get("/cases/c1/receipt", headers=head("bob")).status_code == 404
    assert client.post("/cases/c1/receipt", json={"received": True}, headers=head("bob")).status_code == 404
    assert world.events == []


def test_long_notes_are_refused_and_logged_out_is_refused(world):
    assert client.post("/cases/c1/receipt", json={"received": False, "note": "x" * 501}, headers=head("ann")).status_code == 422
    assert client.get("/cases/c1/receipt").status_code == 401


def test_a_requester_cannot_record_that_a_dispute_was_handled(world):
    assert client.post("/cases/c1/delivery/dispute-handled", json={}, headers=head("ann")).status_code == 403
    assert world.events == []
