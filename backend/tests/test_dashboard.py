from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import dashboard_controller
from app.core import access, security
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.repositories import dashboard_repository, purchase_order_repository, role_repository, user_repository

client = TestClient(app)
NOW = datetime(2026, 10, 10, 12, 0)

TOTALS = {
    "cases_total": 10, "cases_open": 4, "cases_closed": 6, "stock_items": 34, "out_of_stock": 3, "low_stock": 4,
    "suppliers": 3, "purchase_orders": 5, "ordered_total": 210000.0, "ordered_today": 42000.0,
    "awaiting_delivery": 2, "overdue_deliveries": 1, "pending_approvals": 1, "invoices_to_review": 1,
}


# ---------- the trend always has one entry per day ----------

def test_missing_days_are_filled_with_zero_in_order():
    rows = [(date(2026, 10, 8), 3), (date(2026, 10, 10), 1)]
    days = dashboard_controller._fill_days(rows, date(2026, 10, 10))
    assert len(days) == dashboard_controller.TREND_DAYS
    assert days[-1].day == date(2026, 10, 10) and days[-1].count == 1
    assert [d.count for d in days][-3:] == [3, 0, 1]
    assert [d.day for d in days] == sorted(d.day for d in days)


def test_a_quiet_week_is_all_zeros_not_empty():
    assert [d.count for d in dashboard_controller._fill_days([], date(2026, 10, 10))] == [0] * 7


# ---------- the snapshot ----------

@pytest.fixture
def stubbed(monkeypatch):
    repo = dashboard_repository
    monkeypatch.setattr(repo, "totals", lambda today: dict(TOTALS))
    monkeypatch.setattr(repo, "by_stage", lambda: [("awaiting_quotes", 3), ("po_issued", 1)])
    monkeypatch.setattr(repo, "created_per_day", lambda since: [])
    monkeypatch.setattr(repo, "approval_split", lambda: (6, 2))
    monkeypatch.setattr(repo, "average_close_minutes", lambda: 90.0)
    monkeypatch.setattr(repo, "recent_activity", lambda limit=10: [
        SimpleNamespace(event_id=9, case_id="C1", event_type="po.issued", agent_name="PO Agent", created_at=NOW)])
    monkeypatch.setattr(repo, "attention_cases", lambda: [
        SimpleNamespace(case_id="C1", stage="delivery_late", status="open", updated_at=NOW, items_summary="CCTV camera (50)"),
        SimpleNamespace(case_id="C2", stage="awaiting_approval", status="open", updated_at=NOW, items_summary="Laptop (10)"),
    ])
    monkeypatch.setattr(dashboard_controller.approval_agent, "get_approvals", lambda status=None: [
        {"approval_id": "a1", "case_id": "C2", "reasons": ["Amount over the limit"], "created_at": NOW}])
    monkeypatch.setattr(dashboard_controller.invoice_agent, "list_invoices", lambda status=None: [
        {"invoice_id": "i1", "case_id": "C1", "invoice_number": "INV-7", "vendor_name": "Acme",
         "po_number": "PO-1001", "created_at": NOW}])
    monkeypatch.setattr(dashboard_controller.automation, "is_paused", lambda: False)
    monkeypatch.setattr(purchase_order_repository, "sum_auto_approved_since", lambda since: 42000.0)
    monkeypatch.setattr(dashboard_controller.access, "has_permission", lambda role, perm: True)


def snapshot():
    return dashboard_controller.get_snapshot(SimpleNamespace(user_id="u", username="u@x.co", role="admin"))


def test_the_snapshot_carries_the_numbers(stubbed):
    s = snapshot()
    assert s.totals.cases_open == 4 and s.totals.stock_items == 34 and s.totals.pending_approvals == 1
    assert [(x.stage, x.count) for x in s.by_stage] == [("awaiting_quotes", 3), ("po_issued", 1)]
    assert s.spend.ordered_total == 210000.0 and s.spend.auto_approved_today == 42000.0 and s.spend.daily_limit == 200000.0
    assert s.activity[0].event_type == "po.issued" and s.automation_paused is False


def test_rates_are_calculated_not_guessed(stubbed):
    s = snapshot()
    assert s.rates.auto_approval_percent == 75.0 and s.rates.avg_close_minutes == 90.0


def test_with_no_decisions_yet_the_rate_is_unknown_rather_than_zero(stubbed, monkeypatch):
    monkeypatch.setattr(dashboard_repository, "approval_split", lambda: (0, 0))
    assert snapshot().rates.auto_approval_percent is None


def test_attention_counts_every_item_that_needs_a_person_and_names_what_was_asked_for(stubbed):
    s = snapshot()
    assert s.totals.needs_attention == len(s.attention) == 3          # late delivery, approval, bad invoice
    kinds = sorted(a.kind for a in s.attention)
    assert kinds == ["approval", "case", "invoice"]
    approval = next(a for a in s.attention if a.kind == "approval")
    assert "Laptop (10)" in approval.message and "Amount over the limit" in approval.message


def test_someone_who_cannot_see_approvals_gets_no_approval_items(stubbed, monkeypatch):
    monkeypatch.setattr(dashboard_controller.access, "has_permission", lambda role, perm: perm != "approvals:read")
    assert all(a.kind != "approval" for a in snapshot().attention)


def test_a_paused_system_is_reported(stubbed, monkeypatch):
    monkeypatch.setattr(dashboard_controller.automation, "is_paused", lambda: True)
    assert snapshot().automation_paused is True


# ---------- over HTTP ----------

@pytest.fixture
def people(monkeypatch):
    users = {
        "alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
    }
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    access.invalidate()
    yield
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_the_dashboard_needs_a_login():
    assert client.get("/dashboard").status_code == 401


def test_requesters_cannot_see_the_dashboard(people):
    assert client.get("/dashboard", headers=as_("alice", "user")).status_code == 403


def test_staff_get_the_snapshot_over_http(people, stubbed, monkeypatch):
    monkeypatch.setattr(dashboard_controller.access, "has_permission", access.has_permission)
    r = client.get("/dashboard", headers=as_("mgr", "manager"))
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"generated_at", "totals", "by_stage", "created_per_day", "activity", "attention", "spend", "rates"}
    assert len(body["created_per_day"]) == 7
