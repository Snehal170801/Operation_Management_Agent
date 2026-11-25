"""The Accounts tab: an administrator opens a department's account without its password. Strictly limited, always audited."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import user_controller
from app.core import access, security
from app.core.config import settings
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, DEPARTMENTS
from app.main import app
from app.repositories import role_repository, user_repository

client = TestClient(app)


def user(uid, role, active=True, name=None):
    return SimpleNamespace(user_id=uid, username=f"{uid}@x.co", role=role, is_active=active, email=f"{uid}@x.co", display_name=name or uid,
                           locked_until=None, last_login_at=None, created_at=None, failed_attempts=0)


@pytest.fixture
def world(monkeypatch):
    users = {"adm": user("adm", "admin"), "adm2": user("adm2", "admin"), "mgr": user("mgr", "manager"),
             "recv": user("recv", "dept_delivery", name="Receiving"), "off": user("off", "dept_invoice", active=False),
             "req": user("req", "user")}
    roles = {f"dept_{d.key}": set(d.permissions) for d in DEPARTMENTS}
    roles.update({"admin": set(ALL_PERMISSIONS), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]) | {"users:write", "users:read"}, "user": {"cases:read", "cases:create"}})
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: roles)
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(str(uid).lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    audited = []
    monkeypatch.setattr(user_controller.audit, "record", lambda action, **kw: audited.append((action, kw)))
    monkeypatch.setattr("app.controllers.auth_controller._to_user_response",
                        lambda row: __import__("app.models.auth_schemas", fromlist=["UserResponse"]).UserResponse(
                            user_id=row.user_id, username=row.username, email=row.email, display_name=row.display_name, role=row.role,
                            permissions=sorted(roles.get(row.role, set()))))
    access.invalidate()
    yield audited
    access.invalidate()


def as_(uid):
    role = {"adm": "admin", "adm2": "admin", "mgr": "manager", "recv": "dept_delivery", "req": "user"}[uid]
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def open_(actor, target):
    return client.post(f"/users/{target}/open-session", headers=as_(actor))


def test_an_admin_gets_a_one_hour_sign_in_for_a_department_account(world):
    r = open_("adm", "recv")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "recv@x.co" and body["opened_by"] == "adm@x.co" and body["expires_in"] == settings.OPEN_ACCOUNT_MINUTES * 60
    claims = security.decode_access_token(body["access_token"])
    assert claims["sub"] == "recv" and claims["role"] == "dept_delivery" and claims["imp"] == "adm@x.co"


def test_every_use_is_written_to_the_audit_log_with_who_and_as_whom(world):
    open_("adm", "recv")
    action, detail = world[0]
    assert action == "user.open_account" and detail["actor_username"] == "adm@x.co" and detail["detail"]["as"] == "recv@x.co"


def test_the_token_works_only_as_that_account_with_that_accounts_permissions(world):
    token = open_("adm", "recv").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["username"] == "recv@x.co"              # it really is that account
    assert client.post("/approvals/x/approve", headers=headers, json={}).status_code == 403    # but cannot approve
    assert client.post("/users/recv/open-session", headers=headers).status_code == 403          # nor open accounts


def test_someone_who_is_not_an_administrator_cannot_open_accounts_even_with_user_management(world):
    r = open_("mgr", "recv")
    assert r.status_code == 409 and "administrator" in r.json()["detail"] and world == []


def test_a_requester_cannot_open_accounts_at_all(world):
    assert open_("req", "recv").status_code == 403


def test_another_administrators_account_cannot_be_opened(world):
    r = open_("adm", "adm2")
    assert r.status_code == 409 and "administrator's account" in r.json()["detail"]


def test_a_switched_off_account_cannot_be_opened(world):
    assert open_("adm", "off").status_code == 409


def test_an_unknown_account_is_not_found(world):
    assert open_("adm", "ghost").status_code == 404


def test_the_whole_feature_can_be_switched_off(world, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_OPEN_ACCOUNT", False)
    r = open_("adm", "recv")
    assert r.status_code == 409 and "switched off" in r.json()["detail"] and world == []


def test_an_opened_account_cannot_be_used_to_open_another(world):
    # even if that account somehow held user management, the marker on its token stops the chain
    token, _ = security.create_access_token("mgr", "mgr@x.co", "admin", impersonator="adm@x.co")
    r = client.post("/users/recv/open-session", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 409


def test_a_normal_sign_in_carries_no_marker():
    claims = security.decode_access_token(security.create_access_token("u", "u@x.co", "user")[0])
    assert "imp" not in claims
