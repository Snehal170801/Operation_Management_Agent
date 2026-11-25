"""The two experiences: a requester (`user`) sees only their own cases and only the agent flow;
staff see everything. Run over HTTP against in-memory fakes (no database)."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import case_controller
from app.core import access, security
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.repositories import case_repository, role_repository, user_repository

client = TestClient(app)

ALICE_CASE = "aaaaaaaa-0000-4000-8000-000000000001"
BOB_CASE = "bbbbbbbb-0000-4000-8000-000000000002"
NOW = datetime(2026, 10, 1, 12, 0)


def _event(i, event_type, payload=None):
    return {"event_id": i, "event_type": event_type, "agent_name": "Agent", "payload": payload, "created_at": NOW}


EVENTS = [
    _event(1, "case.created", {"requester_id": "alice@x.co"}),
    _event(2, "stock.checked", {"checks": [{"available": 3}]}),
    _event(3, "quote.submitted", {"vendor_id": "v1", "price": 42000}),
    _event(4, "vendor.selected", {"rationale": "cheapest of three"}),
    _event(5, "approval.requested", {"reasons": ["Amount 90,000 exceeds the limit"]}),
    _event(6, "notification.sent", {"kind": "approval_requested", "sent": 2}),
    _event(7, "worker.error", {"error": "LLM down"}),
    _event(8, "stage.sourcing_stalled", None),
    _event(9, "po.issued", {"po_number": "PO-1001", "total_amount": 42000}),
]


@pytest.fixture
def world(monkeypatch):
    users = {
        "alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
        "bob": SimpleNamespace(user_id="bob", username="bob@x.co", role="user", is_active=True),
        "boss": SimpleNamespace(user_id="boss", username="boss@x.co", role="admin", is_active=True),
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
        "view": SimpleNamespace(user_id="view", username="view@x.co", role="viewer", is_active=True),
    }
    cases = {ALICE_CASE: "alice@x.co", BOB_CASE: "bob@x.co"}
    log = SimpleNamespace(listed_for=[], started=[], recent=0)

    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]),
        "viewer": set(DEFAULT_ROLE_PERMISSIONS["viewer"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"]),
    })
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr(case_repository, "find_case_by_id",
                        lambda cid: SimpleNamespace(requester_id=cases[cid]) if cid in cases else None)

    ops = case_controller.operations_agent
    monkeypatch.setattr(ops, "get_all_cases", lambda requester_id=None: log.listed_for.append(requester_id) or [])
    monkeypatch.setattr(ops, "get_case_status", lambda cid: {
        "case_id": cid, "requester_id": cases[cid], "stage": "awaiting_approval", "status": "open",
        "summary": None, "created_at": NOW, "updated_at": NOW})
    monkeypatch.setattr(ops, "get_case_events", lambda cid: [dict(e) for e in EVENTS])
    monkeypatch.setattr(ops, "count_recent_cases", lambda requester_id, hours=24: log.recent)
    monkeypatch.setattr(case_controller.case_pipeline, "start_case",
                        lambda requester_id, raw_request, **kw: log.started.append(requester_id) or "new-case")
    monkeypatch.setattr("app.controllers.purchase_controller.purchase_agent.get_purchase_request", lambda cid: {
        "purchase_request_id": "p1", "case_id": cid, "cost_center": None, "raw_request": "10 laptops",
        "items": [{"description": "Laptop", "quantity": 10}], "created_at": NOW})
    monkeypatch.setattr("app.core.audit.record", lambda *a, **k: None)
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    monkeypatch.setattr("app.controllers.case_controller.audit.record", lambda *a, **k: None)
    access.invalidate()
    yield log
    access.invalidate()


def as_(uid):
    role = {"alice": "user", "bob": "user", "boss": "admin", "mgr": "manager", "view": "viewer"}[uid]
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


# ---------- what each role is allowed ----------

def test_requester_role_has_only_own_read_and_create():
    assert DEFAULT_ROLE_PERMISSIONS["user"] == frozenset({"cases:read", "cases:create"})


def test_existing_staff_roles_keep_full_case_visibility():
    for role in ("viewer", "manager"):
        assert "cases:read_all" in DEFAULT_ROLE_PERMISSIONS[role]


# ---------- a requester only sees their own cases ----------

def test_requester_list_is_limited_to_themselves(world):
    assert client.get("/cases", headers=as_("alice")).status_code == 200
    assert world.listed_for == ["alice@x.co"]


def test_staff_list_is_not_limited(world):
    client.get("/cases", headers=as_("boss"))
    client.get("/cases", headers=as_("view"))
    assert world.listed_for == [None, None]


def test_requester_can_open_own_case_but_not_someone_elses(world):
    assert client.get(f"/cases/{ALICE_CASE}", headers=as_("alice")).status_code == 200
    # 404 rather than 403, so ids cannot be probed
    assert client.get(f"/cases/{BOB_CASE}", headers=as_("alice")).status_code == 404
    assert client.get(f"/cases/{BOB_CASE}/events", headers=as_("alice")).status_code == 404
    assert client.get(f"/purchase-requests/{BOB_CASE}", headers=as_("alice")).status_code == 404


def test_requester_can_read_own_purchase_request(world):
    assert client.get(f"/purchase-requests/{ALICE_CASE}", headers=as_("alice")).status_code == 200


def test_staff_can_open_any_case(world):
    assert client.get(f"/cases/{BOB_CASE}", headers=as_("boss")).status_code == 200
    assert client.get(f"/purchase-requests/{BOB_CASE}", headers=as_("mgr")).status_code == 200


# ---------- a requester sees the flow, not the internals ----------

def test_requester_timeline_hides_internals_and_payloads(world):
    body = client.get(f"/cases/{ALICE_CASE}/events", headers=as_("alice")).json()
    types = [e["event_type"] for e in body]
    assert types == ["case.created", "stock.checked", "quote.submitted", "vendor.selected",
                     "approval.requested", "po.issued"]
    assert all(e["payload"] is None for e in body)
    raw = str(body)
    for secret in ("42000", "90,000", "LLM down", "cheapest", "PO-1001"):
        assert secret not in raw


def test_staff_timeline_is_complete(world):
    body = client.get(f"/cases/{ALICE_CASE}/events", headers=as_("boss")).json()
    assert len(body) == len(EVENTS)
    assert any(e["payload"] for e in body)


# ---------- creating requests ----------

def test_requester_cannot_file_as_someone_else(world):
    r = client.post("/cases", headers=as_("alice"), json={"raw_request": "10 laptops", "requester_id": "ceo@x.co"})
    assert r.status_code == 200
    assert world.started == ["alice@x.co"]


def test_requester_id_is_optional(world):
    assert client.post("/cases", headers=as_("alice"), json={"raw_request": "10 laptops"}).status_code == 200
    assert world.started == ["alice@x.co"]


def test_staff_may_file_on_behalf_of_someone(world):
    client.post("/cases", headers=as_("mgr"), json={"raw_request": "10 laptops", "requester_id": "bob@x.co"})
    client.post("/cases", headers=as_("mgr"), json={"raw_request": "10 laptops"})
    assert world.started == ["bob@x.co", "mgr@x.co"]


def test_viewer_cannot_create_cases(world):
    assert client.post("/cases", headers=as_("view"), json={"raw_request": "x"}).status_code == 403


def test_requester_is_rate_limited(world):
    world.recent = 20
    r = client.post("/cases", headers=as_("alice"), json={"raw_request": "10 laptops"})
    assert r.status_code == 429 and world.started == []


def test_staff_are_not_rate_limited(world):
    world.recent = 999
    assert client.post("/cases", headers=as_("mgr"), json={"raw_request": "10 laptops"}).status_code == 200


@pytest.mark.parametrize("body", [{"raw_request": ""}, {"raw_request": "x" * 2001}, {}])
def test_request_text_is_validated(world, body):
    assert client.post("/cases", headers=as_("alice"), json=body).status_code == 422


# ---------- everything else is staff-only ----------

@pytest.mark.parametrize("method,path", [
    ("get", "/stock"), ("get", "/vendors"), ("get", "/approvals"),
    ("get", f"/cases/{ALICE_CASE}/quotes"), ("get", f"/cases/{ALICE_CASE}/rfqs"),
    ("post", f"/cases/{ALICE_CASE}/rank-vendors"),
    ("get", f"/cases/{ALICE_CASE}/purchase-order"), ("post", f"/cases/{ALICE_CASE}/purchase-order"),
    ("get", f"/cases/{ALICE_CASE}/delivery"), ("post", f"/cases/{ALICE_CASE}/delivery/received"),
    ("get", "/users"), ("get", "/users/permissions"), ("get", "/audit"), ("get", "/system/health"),
])
def test_requester_is_locked_out_of_staff_areas(world, method, path):
    r = getattr(client, method)(path, headers=as_("alice"))
    assert r.status_code == 403, path
