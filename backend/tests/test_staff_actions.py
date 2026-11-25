"""Staff actions record WHO did them from the signed-in session, never from the request body."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import approval_controller, delivery_controller
from app.core.permissions import ALL_PERMISSIONS
from app.core import access, security
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.repositories import role_repository, user_repository

client = TestClient(app)
CASE = "aaaaaaaa-0000-4000-8000-000000000001"


@pytest.fixture
def staff(monkeypatch):
    users = {
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
        "view": SimpleNamespace(user_id="view", username="view@x.co", role="viewer", is_active=True),
        "adm": SimpleNamespace(user_id="adm", username="adm@x.co", role="admin", is_active=True),
    }
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(ALL_PERMISSIONS), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]),
        "viewer": set(DEFAULT_ROLE_PERMISSIONS["viewer"]),
    })
    # who asked for the purchase (the controller checks nobody approves their own)
    monkeypatch.setattr(approval_controller.approval_agent, "get_approval", lambda aid: {"case_id": CASE})
    monkeypatch.setattr(approval_controller.operations_agent, "get_case_status", lambda cid: {"requester_id": "alice@x.co"})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    audited = []
    monkeypatch.setattr(approval_controller.audit, "record", lambda action, **kw: audited.append((action, kw)))
    monkeypatch.setattr(delivery_controller.audit, "record", lambda action, **kw: audited.append((action, kw)))
    access.invalidate()
    yield audited
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


APPROVAL = {
    "approval_id": "ap1", "case_id": CASE, "approval_type": "vendor_selection", "status": "approved",
    "reasons": [], "decided_by": "mgr@x.co", "decision_note": None, "created_at": "2026-10-01T00:00:00",
    "decided_at": None,
}


def test_approval_is_recorded_under_the_signed_in_user_not_the_body(staff, monkeypatch):
    calls = []
    monkeypatch.setattr(approval_controller.case_pipeline, "decide_approval",
                        lambda aid, approve, by, note: calls.append((aid, approve, by, note)) or APPROVAL)
    r = client.post("/approvals/ap1/approve", headers=as_("mgr", "manager"),
                    json={"note": "ok", "decided_by": "the.ceo@x.co"})
    assert r.status_code == 200
    assert calls == [("ap1", True, "mgr@x.co", "ok")]
    assert staff[0][0] == "approval.approve" and staff[0][1]["actor_username"] == "mgr@x.co"


def test_rejection_is_recorded_and_audited(staff, monkeypatch):
    calls = []
    monkeypatch.setattr(approval_controller.case_pipeline, "decide_approval",
                        lambda aid, approve, by, note: calls.append((approve, by)) or {**APPROVAL, "status": "rejected"})
    assert client.post("/approvals/ap1/reject", headers=as_("mgr", "manager"), json={}).status_code == 200
    assert calls == [(False, "mgr@x.co")]
    assert staff[0][0] == "approval.reject"


def test_viewer_cannot_decide_approvals(staff):
    assert client.post("/approvals/ap1/approve", headers=as_("view", "viewer"), json={}).status_code == 403


def test_delivery_is_confirmed_under_the_signed_in_user(staff, monkeypatch):
    calls = []
    monkeypatch.setattr(delivery_controller.case_pipeline, "confirm_delivery",
                        lambda cid, by, note, items=None: calls.append((cid, by, note)) or {
                            "case_id": cid, "po_number": "PO-1001", "vendor_name": "Acme",
                            "delivery_status": "delivered", "chase_count": 0})
    r = client.post(f"/cases/{CASE}/delivery/received", headers=as_("mgr", "manager"),
                    json={"note": "all boxes ok", "received_by": "someone.else"})
    assert r.status_code == 200
    assert calls == [(CASE, "mgr@x.co", "all boxes ok")]
    assert staff[0][0] == "delivery.confirm"


def test_viewer_cannot_confirm_delivery(staff):
    assert client.post(f"/cases/{CASE}/delivery/received", headers=as_("view", "viewer"), json={}).status_code == 403


def test_nobody_approves_a_purchase_they_asked_for(staff, monkeypatch):
    monkeypatch.setattr(approval_controller.operations_agent, "get_case_status", lambda cid: {"requester_id": "mgr@x.co"})
    monkeypatch.setattr(approval_controller.case_pipeline, "decide_approval", lambda *a: pytest.fail("must not decide"))
    r = client.post("/approvals/ap1/approve", headers=as_("mgr", "manager"), json={})
    assert r.status_code == 409 and "asked for this purchase" in r.json()["detail"]


def test_an_admin_may_approve_their_own_request_but_it_is_marked_in_the_audit_log(staff, monkeypatch):
    monkeypatch.setattr(approval_controller.operations_agent, "get_case_status", lambda cid: {"requester_id": "adm@x.co"})
    monkeypatch.setattr(approval_controller.case_pipeline, "decide_approval", lambda aid, approve, by, note: APPROVAL)
    assert client.post("/approvals/ap1/approve", headers=as_("adm", "admin"), json={}).status_code == 200
    assert staff[0][1]["detail"]["override"] == "admin approved their own request"
