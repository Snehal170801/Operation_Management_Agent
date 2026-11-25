"""One department per agent: each can do its own job and nothing else, and hears only about its own problems."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import access, security
from app.core.agent_steps import FLOW_AGENTS
from app.core.notification_feed import staff_items
from app.core.permissions import ALL_PERMISSIONS, ALERT_PERMISSION, DEFAULT_ROLE_PERMISSIONS, DEPARTMENTS
from app.main import app
from app.repositories import role_repository, user_repository

# a guard that lets the request through but then fails inside (no database here) answers 500, never 403
client = TestClient(app, raise_server_exceptions=False)
CASE = "aaaaaaaa-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 2, 12, 0)

ACTIONS = {
    "delivery:confirm": ("post", f"/cases/{CASE}/delivery/received", {}),
    "invoices:decide": ("post", "/invoices/i1/approve", {}),
    "po:manage": ("post", f"/cases/{CASE}/purchase-order", None),
    "approvals:write": ("post", "/approvals/ap1/approve", {}),
    "vendors:write": ("post", "/vendors", {"name": "X", "reliability_score": 4}),
    "stock:write": ("post", "/stock", {"item_description": "x", "quantity_available": 1}),
}


def dept(key):
    return next(d for d in DEPARTMENTS if d.key == key)


@pytest.fixture
def people(monkeypatch):
    users = {d.key: SimpleNamespace(user_id=d.key, username=f"{d.key}@x.co", role=f"dept_{d.key}", is_active=True) for d in DEPARTMENTS}
    users["requester"] = SimpleNamespace(user_id="requester", username="r@x.co", role="user", is_active=True)
    roles = {f"dept_{d.key}": set(d.permissions) for d in DEPARTMENTS}
    roles.update({"user": set(DEFAULT_ROLE_PERMISSIONS["user"]), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]), "admin": set(ALL_PERMISSIONS)})
    users["manager"] = SimpleNamespace(user_id="manager", username="m@x.co", role="manager", is_active=True)
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: roles)
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    access.invalidate()
    yield
    access.invalidate()


def as_(who):
    role = "user" if who == "requester" else "manager" if who == "manager" else f"dept_{who}"
    token, _ = security.create_access_token(who, f"{who}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def call(who, permission):
    method, path, body = ACTIONS[permission]
    return getattr(client, method)(path, headers=as_(who), **({"json": body} if body is not None else {})).status_code


def test_there_is_one_department_for_each_stage_agent_and_they_ask_for_real_permissions():
    assert [d.agent for d in DEPARTMENTS] == list(FLOW_AGENTS)
    assert len({d.key for d in DEPARTMENTS}) == len(DEPARTMENTS)
    for d in DEPARTMENTS:
        assert set(d.permissions) <= ALL_PERMISSIONS, d.key
        assert "cases:read_all" in d.permissions and "users:write" not in d.permissions   # they see cases, never manage users


def test_every_kind_of_problem_has_a_department_that_can_actually_deal_with_it():
    for kind, permission in ALERT_PERMISSION.items():
        assert any(permission in d.permissions for d in DEPARTMENTS), kind


@pytest.mark.parametrize("key, permission", [("delivery", "delivery:confirm"), ("invoice", "invoices:decide"), ("po", "po:manage"),
                                              ("approval", "approvals:write"), ("vendor", "vendors:write"), ("procurement", "stock:write")])
def test_a_department_can_do_its_own_job(people, key, permission):
    assert call(key, permission) != 403


def test_a_department_cannot_do_another_departments_job(people):
    # Receiving confirms goods but cannot decide an invoice; Accounts decides invoices but cannot confirm goods
    assert call("delivery", "invoices:decide") == 403 and call("invoice", "delivery:confirm") == 403
    # the approvers cannot touch purchase orders, receiving cannot approve, stores cannot change suppliers
    assert call("approval", "po:manage") == 403 and call("delivery", "approvals:write") == 403 and call("procurement", "vendors:write") == 403
    # the PO desk cannot decide invoices or confirm goods
    assert call("po", "invoices:decide") == 403 and call("po", "delivery:confirm") == 403


def test_a_requester_can_do_none_of_it(people):
    for permission in ACTIONS:
        assert call("requester", permission) == 403, permission


def test_the_all_rounder_manager_role_still_can_do_everything(people):
    for permission in ACTIONS:
        assert call("manager", permission) != 403, permission


# ------------------------------------------------------------------------------------- the bell

def case(stage):
    return {"case_id": f"c-{stage}", "stage": stage, "status": "open", "items_summary": "Cameras", "updated_at": NOW}


STUCK = [case("sourcing_stalled"), case("po_send_failed"), case("delivery_late")]
APPROVAL = [{"approval_id": "a1", "case_id": "c-x", "reasons": ["Too big"], "created_at": NOW}]
INVOICE = [{"invoice_id": "i1", "case_id": "c-x", "invoice_number": "INV-1", "vendor_name": "Acme", "po_number": "PO-1", "created_at": NOW}]


def kinds(perms):
    items = staff_items(APPROVAL, STUCK + [], INVOICE, can=lambda p: p in perms)
    return sorted(i["title"] for i in items)


def test_each_department_sees_only_its_own_problems_in_the_bell():
    assert kinds({"approvals:write"}) == ["Approval needed"]
    assert kinds({"delivery:confirm"}) == ["Delivery overdue"]
    assert kinds({"invoices:decide"}) == ["Invoice needs review"]
    assert kinds({"po:manage"}) == ["Purchase order not sent"]
    assert kinds({"vendors:write"}) == ["Suppliers not responding"]
    assert kinds(set()) == []


def test_a_person_in_two_departments_sees_both_and_the_admin_sees_everything():
    assert kinds({"delivery:confirm", "invoices:decide"}) == ["Delivery overdue", "Invoice needs review"]
    assert len(kinds(ALL_PERMISSIONS)) == 5
    assert len(staff_items(APPROVAL, STUCK, INVOICE)) == 5          # no filter given: everything, as before


def test_every_departments_permissions_can_be_ticked_with_the_boxes_on_the_users_screen():
    """The Users form only offers whole boxes (a level grants a fixed bundle), so a department's set must be
    exactly the union of boxes that fit inside it; otherwise saving the form would silently drop some."""
    from app.core.permissions import CATALOG
    for d in DEPARTMENTS:
        held = set(d.permissions)
        covered = set()
        for group in CATALOG:
            for level in group.levels:
                if set(level.permissions) <= held:
                    covered |= set(level.permissions)
        assert covered == held, (d.key, sorted(held - covered))
