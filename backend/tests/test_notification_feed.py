from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import notification_controller
from app.core import access, security
from app.core.notification_feed import MAX_ITEMS, requester_items, staff_items
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.repositories import role_repository, user_repository

NOW = datetime(2026, 10, 10, 12, 0)


def case(case_id, stage, status="open", updated=NOW, summary="50 CCTV camera (50)", requester="ravi@x.co"):
    return {"case_id": case_id, "requester_id": requester, "stage": stage, "status": status,
            "items_summary": summary, "updated_at": updated}


# ---------- staff: what needs a person ----------

def test_staff_see_pending_approvals_with_the_first_reason():
    approvals = [{"approval_id": "a1", "case_id": "c1", "reasons": ["Amount 90,000 exceeds the limit", "x"],
                  "created_at": NOW}]
    [item] = staff_items(approvals, [case("c1", "awaiting_approval")], [])
    assert item["kind"] == "approval" and item["requires_action"] and item["link"] == "/approvals"
    assert "Amount 90,000" in item["message"] and "50 CCTV camera" in item["message"]


@pytest.mark.parametrize("stage", ["sourcing_stalled", "po_send_failed", "po_failed", "delivery_late"])
def test_staff_see_stuck_cases(stage):
    [item] = staff_items([], [case("c1", stage)], [])
    assert item["kind"] == "case" and item["link"] == "/cases/c1" and item["requires_action"]


@pytest.mark.parametrize("stage", ["awaiting_quotes", "po_issued", "delivered", "created"])
def test_healthy_cases_do_not_ring_the_bell(stage):
    assert staff_items([], [case("c1", stage)], []) == []


def test_closed_cases_are_not_alerts_even_if_the_stage_was_bad():
    assert staff_items([], [case("c1", "delivery_late", status="closed")], []) == []


def test_staff_see_mismatched_invoices():
    inv = [{"invoice_id": "i1", "case_id": "c1", "invoice_number": "INV-7", "vendor_name": "Acme",
            "po_number": "PO-1001", "created_at": NOW}]
    [item] = staff_items([], [case("c1", "delivered")], inv)
    assert item["kind"] == "invoice" and "INV-7" in item["message"] and "PO-1001" in item["message"]


def test_newest_first_and_capped():
    cases = [case(f"c{i}", "sourcing_stalled", updated=NOW + timedelta(minutes=i)) for i in range(MAX_ITEMS + 10)]
    items = staff_items([], cases, [])
    assert len(items) == MAX_ITEMS
    assert items[0]["created_at"] > items[-1]["created_at"]


# ---------- requester: progress on their own requests ----------

def test_requester_gets_friendly_milestones_without_internals():
    items = requester_items([case("c1", "po_issued"), case("c2", "fulfilled_from_stock", status="closed")], NOW)
    assert {i["title"] for i in items} == {"Order placed", "Available in stock"}
    assert all(not i["requires_action"] and i["kind"] == "my_request" for i in items)
    assert all(i["link"].startswith("/requests/") for i in items)


def test_requester_is_never_told_about_internal_stages():
    for stage in ("sourcing_needed", "awaiting_quotes", "vendor_selected", "approved", "po_send_failed"):
        assert requester_items([case("c1", stage)], NOW) == []


def test_a_requester_is_not_alarmed_with_internal_failure_wording():
    [item] = requester_items([case("c1", "sourcing_stalled")], NOW)
    assert item["title"] == "Taking longer than usual"
    assert "supplier" not in item["message"].lower() and "quote" not in item["message"].lower()


def test_old_milestones_drop_off():
    assert requester_items([case("c1", "po_issued", updated=NOW - timedelta(days=30))], NOW) == []


def test_a_completed_case_reads_as_complete():
    [item] = requester_items([case("c1", "completed", status="closed")], NOW)
    assert item["title"] == "Request complete"


# ---------- over HTTP: always scoped to the caller ----------

client = TestClient(app)


@pytest.fixture
def world(monkeypatch):
    users = {
        "alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
    }
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    asked = []
    now = datetime.now()
    all_cases = [case("c1", "po_issued", updated=now, requester="alice@x.co"),
                 case("c2", "sourcing_stalled", updated=now, requester="bob@x.co")]

    def get_all_cases(requester_id=None):
        asked.append(requester_id)
        return [c for c in all_cases if requester_id is None or c["requester_id"] == requester_id]

    monkeypatch.setattr(notification_controller.operations_agent, "get_all_cases", get_all_cases)
    monkeypatch.setattr(notification_controller.approval_agent, "get_approvals", lambda status=None: [])
    monkeypatch.setattr(notification_controller.invoice_agent, "list_invoices", lambda status=None: [])
    access.invalidate()
    yield asked
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_the_bell_needs_a_signed_in_user():
    assert client.get("/notifications").status_code == 401


def test_a_requester_only_ever_sees_their_own_requests(world):
    body = client.get("/notifications", headers=as_("alice", "user")).json()
    assert world == ["alice@x.co"]
    assert [n["link"] for n in body] == ["/requests/c1"]       # Bob's stalled case is not in it


def test_staff_see_everything_that_needs_them(world):
    body = client.get("/notifications", headers=as_("mgr", "manager")).json()
    assert world == [None]
    assert [n["link"] for n in body] == ["/cases/c2"] and body[0]["requires_action"] is True
