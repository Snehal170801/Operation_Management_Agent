"""Per-user access rules, run against in-memory fakes of the user / permission-set tables (no database)."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.controllers import user_controller
from app.core import access, security
from app.core.exceptions import InvalidInput, InvalidToken, RuleViolation
from app.core.permissions import (
    ADMIN_ROLE,
    ALL_PERMISSIONS,
    CATALOG,
    DEFAULT_ROLE_PERMISSIONS,
    is_private_role,
    private_role_name,
)
from app.main import app
from app.models.auth_schemas import CreateUserRequest, CurrentUser, UpdateUserRequest
from app.repositories import role_repository, user_repository

client = TestClient(app)
NOW = datetime(2026, 10, 1, 12, 0, 0)


@pytest.fixture
def db(monkeypatch):
    """Mutable fake tables: permission sets (by name) and users, plus a log of audit/session calls."""
    state = SimpleNamespace(
        roles={
            "admin": set(),  # deliberately empty: admin must still hold everything
            "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]),
            "viewer": set(DEFAULT_ROLE_PERMISSIONS["viewer"]),
            "user": set(DEFAULT_ROLE_PERMISSIONS["user"]),
        },
        users={},
        audit=[],
        revoked=[],
    )

    def add_user(uid, role, active=True, email=None):
        email = email or f"{uid}@x.co"
        state.users[uid.lower()] = SimpleNamespace(
            user_id=uid, username=email, email=email, display_name=None, role=role, is_active=active,
            locked_until=None, last_login_at=None, created_at=NOW,
        )

    def create_user(username, password_hash, role, display_name, email=None, user_id=None):
        add_user(user_id, role, email=email or username)
        return user_id

    def update_user(user_id, display_name, role, is_active, email=None):
        u = state.users[user_id.lower()]
        if role is not None:
            u.role = role
        if is_active is not None:
            u.is_active = is_active
        if email:
            u.email = u.username = email

    def create_role(name, display_name, description, permissions):
        assert name not in state.roles, f"set {name} already exists"
        state.roles[name] = set(permissions)

    def update_role(name, display_name, description, permissions):
        if permissions is not None:
            state.roles[name] = set(permissions)

    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {k: set(v) for k, v in state.roles.items()})
    monkeypatch.setattr(role_repository, "create_role", create_role)
    monkeypatch.setattr(role_repository, "update_role", update_role)
    monkeypatch.setattr(role_repository, "delete_role", lambda name: state.roles.pop(name, None))
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: state.users.get(uid.lower()))
    monkeypatch.setattr(
        user_repository, "find_user_by_identifier",
        lambda ident: next((u for u in state.users.values() if ident.lower() in (u.username.lower(), (u.email or "").lower())), None),
    )
    monkeypatch.setattr(user_repository, "create_user", create_user)
    monkeypatch.setattr(user_repository, "update_user", update_user)
    monkeypatch.setattr(
        user_repository, "count_active_admins",
        lambda: sum(1 for u in state.users.values() if u.role == ADMIN_ROLE and u.is_active),
    )
    monkeypatch.setattr(user_repository, "revoke_all_sessions", lambda uid: state.revoked.append(uid))
    monkeypatch.setattr(user_repository, "find_all_users", lambda: list(state.users.values()))
    record = lambda action, **kw: state.audit.append((action, kw))  # noqa: E731
    monkeypatch.setattr("app.core.audit.record", record)
    monkeypatch.setattr("app.api.deps.audit.record", record)
    monkeypatch.setattr("app.controllers.user_controller.audit.record", record)
    access.invalidate()

    state.add_user = add_user
    yield state
    access.invalidate()


def auth(uid):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", "ignored")
    return {"Authorization": f"Bearer {token}"}


def me(db, uid):
    u = db.users[uid.lower()]
    return CurrentUser(user_id=u.user_id, username=u.username, role=u.role)


# ---------- catalog ----------

def test_catalog_is_consistent():
    keys = [p.key for g in CATALOG for p in g.permissions]
    assert len(keys) == len(set(keys)), "duplicate permission key"
    for perms in DEFAULT_ROLE_PERMISSIONS.values():
        assert perms <= ALL_PERMISSIONS
    assert all(k.count(":") == 1 for k in keys)


def test_every_level_only_grants_real_permissions_of_its_own_module():
    for group in CATALOG:
        own = {p.key for p in group.permissions}
        level_keys = {lv.key for lv in group.levels}
        assert group.levels, f"{group.resource} has no checkbox"
        for lv in group.levels:
            assert set(lv.permissions) <= own, f"{group.resource}/{lv.key} grants permissions outside its module"
            assert set(lv.implies) <= level_keys, f"{group.resource}/{lv.key} implies a level that doesn't exist"


def test_crud_includes_read_and_every_write_permission_is_reachable():
    for group in CATALOG:
        by_key = {lv.key: lv for lv in group.levels}
        if "crud" in by_key:
            assert set(by_key["read"].permissions) <= set(by_key["crud"].permissions)
        reachable = {p for lv in group.levels for p in lv.permissions}
        assert {p.key for p in group.permissions} <= reachable, f"{group.resource}: a permission can't be ticked"


# ---------- live authorization ----------

def test_admin_always_has_everything_even_if_db_says_otherwise(db):
    assert access.permissions_for_role(ADMIN_ROLE) == ALL_PERMISSIONS


def test_unknown_set_has_nothing(db):
    assert access.permissions_for_role("ghost") == frozenset()


def test_stale_or_unknown_permission_strings_grant_nothing(db):
    db.roles["viewer"].add("nuclear:launch")
    access.invalidate()
    assert "nuclear:launch" not in access.permissions_for_role("viewer")


def test_roles_pages_are_gone_from_the_api(db):
    db.add_user("a1", ADMIN_ROLE)
    for path in ("/roles", "/users/roles", "/roles/permissions"):
        assert client.get(path, headers=auth("a1")).status_code in (404, 405)


def test_read_only_user_cannot_write_or_administer(db):
    db.add_user("u1", "viewer")
    h = auth("u1")
    assert client.post("/stock", json={}, headers=h).status_code == 403
    assert client.get("/users", headers=h).status_code == 403
    assert client.get("/users/permissions", headers=h).status_code == 403
    assert client.get("/audit", headers=h).status_code == 403
    assert client.get("/system/health", headers=h).status_code == 403


def test_denials_are_audited(db):
    db.add_user("u1", "viewer")
    client.get("/users", headers=auth("u1"))
    _, kw = next(x for x in db.audit if x[0] == "authz.denied")
    assert kw["outcome"] == "denied" and kw["detail"]["permission"] == "users:read"


def test_crud_user_passes_the_write_guard_but_not_admin_areas(db):
    db.add_user("m1", "manager")
    h = auth("m1")
    assert client.post("/stock", json={}, headers=h).status_code == 422  # authorised; the body is invalid
    assert client.get("/users", headers=h).status_code == 403


def test_permissions_come_from_the_database_not_the_token(db):
    db.add_user("u1", "viewer")
    token, _ = security.create_access_token("u1", "u1@x.co", "admin")  # a token claiming admin
    assert client.get("/users", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_deactivated_user_is_locked_out_immediately(db):
    db.add_user("u1", "manager")
    token, _ = security.create_access_token("u1", "u1@x.co", "manager")
    creds = SimpleNamespace(credentials=token)
    assert get_current_user(creds).user_id == "u1"
    db.users["u1"].is_active = False
    access.invalidate()
    with pytest.raises(InvalidToken):
        get_current_user(creds)


def test_deleted_user_token_is_rejected(db):
    assert client.get("/cases", headers=auth("nobody")).status_code == 401


# ---------- the checkmark rules (user_controller) ----------

def test_create_user_gets_their_own_private_set_with_exactly_the_ticks(db):
    db.add_user("boss", ADMIN_ROLE)
    out = user_controller.create_user(
        CreateUserRequest(email="Ann@X.co", password="Valid@1234", permissions=["stock:read", "stock:write"]),
        me(db, "boss"),
    )
    row = db.users[out.user_id.lower()]
    assert is_private_role(row.role) and row.role == private_role_name(out.user_id)
    assert db.roles[row.role] == {"stock:read", "stock:write"}
    assert out.permissions == ["stock:read", "stock:write"] and not out.is_admin
    assert out.username == "ann@x.co"


def test_cannot_give_permissions_you_dont_have(db):
    db.add_user("m1", "manager")  # manager has no users:write / audit:read
    with pytest.raises(RuleViolation):
        user_controller.create_user(
            CreateUserRequest(email="a@x.co", password="Valid@1234", permissions=["audit:read"]), me(db, "m1")
        )


def test_unknown_permissions_are_rejected(db):
    db.add_user("boss", ADMIN_ROLE)
    with pytest.raises(InvalidInput):
        user_controller.create_user(
            CreateUserRequest(email="a@x.co", password="Valid@1234", permissions=["made:up"]), me(db, "boss")
        )


def test_only_an_admin_can_create_an_admin(db):
    db.add_user("m1", "manager")
    with pytest.raises(RuleViolation):
        user_controller.create_user(
            CreateUserRequest(email="a@x.co", password="Valid@1234", is_admin=True), me(db, "m1")
        )
    db.add_user("boss", ADMIN_ROLE)
    out = user_controller.create_user(
        CreateUserRequest(email="a@x.co", password="Valid@1234", is_admin=True), me(db, "boss")
    )
    assert out.is_admin and db.users[out.user_id.lower()].role == ADMIN_ROLE
    assert not any(is_private_role(r) for r in db.roles), "an admin needs no private set"


def test_editing_ticks_updates_that_users_set_only(db):
    db.add_user("boss", ADMIN_ROLE)
    created = user_controller.create_user(
        CreateUserRequest(email="a@x.co", password="Valid@1234", permissions=["stock:read"]), me(db, "boss")
    )
    other = user_controller.create_user(
        CreateUserRequest(email="b@x.co", password="Valid@1234", permissions=["stock:read"]), me(db, "boss")
    )
    out = user_controller.update_user(
        created.user_id, UpdateUserRequest(permissions=["stock:read", "stock:write", "vendors:read"]), me(db, "boss")
    )
    assert set(out.permissions) == {"stock:read", "stock:write", "vendors:read"}
    assert db.roles[db.users[other.user_id.lower()].role] == {"stock:read"}, "other users must be untouched"
    _, kw = next(x for x in reversed(db.audit) if x[0] == "user.update")
    assert kw["detail"]["added"] == ["stock:write", "vendors:read"] and kw["detail"]["removed"] == []


def test_a_user_on_a_shared_set_gets_their_own_on_first_edit(db):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("legacy", "manager")  # still on the shared built-in 'manager' set
    before = set(db.roles["manager"])
    user_controller.update_user("legacy", UpdateUserRequest(permissions=["stock:read"]), me(db, "boss"))
    assert is_private_role(db.users["legacy"].role)
    assert db.roles[db.users["legacy"].role] == {"stock:read"}
    assert db.roles["manager"] == before, "the shared set must not be changed by editing one user"


def test_promote_and_demote_admin(db):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("boss2", ADMIN_ROLE)
    created = user_controller.create_user(
        CreateUserRequest(email="a@x.co", password="Valid@1234", permissions=["stock:read"]), me(db, "boss")
    )
    out = user_controller.update_user(created.user_id, UpdateUserRequest(is_admin=True), me(db, "boss"))
    assert out.is_admin and set(out.permissions) == set(ALL_PERMISSIONS)
    assert not any(is_private_role(r) for r in db.roles), "the old private set should be cleaned up"

    with pytest.raises(RuleViolation, match="Choose what"):
        user_controller.update_user(created.user_id, UpdateUserRequest(is_admin=False), me(db, "boss"))
    back = user_controller.update_user(
        created.user_id, UpdateUserRequest(is_admin=False, permissions=["stock:read"]), me(db, "boss")
    )
    assert not back.is_admin and back.permissions == ["stock:read"]


def test_only_an_admin_can_grant_or_remove_admin(db):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("m1", "manager")
    db.add_user("v1", "viewer")
    with pytest.raises(RuleViolation):
        user_controller.update_user("v1", UpdateUserRequest(is_admin=True), me(db, "m1"))
    with pytest.raises(RuleViolation):  # a non-admin may not touch someone more powerful at all
        user_controller.update_user("boss", UpdateUserRequest(is_admin=False, permissions=[]), me(db, "m1"))


def test_you_cannot_demote_or_deactivate_yourself_as_an_admin(db):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("boss2", ADMIN_ROLE)
    with pytest.raises(RuleViolation, match="your own admin"):
        user_controller.update_user("boss", UpdateUserRequest(is_admin=False, permissions=[]), me(db, "boss"))
    with pytest.raises(RuleViolation, match="your own admin"):
        user_controller.update_user("boss", UpdateUserRequest(is_active=False), me(db, "boss"))


def test_the_last_active_admin_is_protected(db):
    """Defence in depth: even if a stale or racing request reaches this point, the last admin stays."""
    db.add_user("ghost", ADMIN_ROLE, active=False)  # an admin whose account was just switched off
    db.add_user("only", ADMIN_ROLE)  # the one remaining active admin
    with pytest.raises(RuleViolation, match="at least one active admin"):
        user_controller.update_user("only", UpdateUserRequest(is_active=False), me(db, "ghost"))
    with pytest.raises(RuleViolation, match="at least one active admin"):
        user_controller.update_user("only", UpdateUserRequest(is_admin=False, permissions=[]), me(db, "ghost"))


def test_you_cannot_remove_your_own_ability_to_manage_users(db):
    db.add_user("boss", ADMIN_ROLE)
    out = user_controller.create_user(
        CreateUserRequest(email="hr@x.co", password="Valid@1234", permissions=["users:read", "users:write"]),
        me(db, "boss"),
    )
    hr = me(db, out.user_id)
    with pytest.raises(RuleViolation, match="manage users"):
        user_controller.update_user(out.user_id, UpdateUserRequest(permissions=["users:read"]), hr)
    # changing other ticks while keeping users:write is fine
    kept = user_controller.update_user(
        out.user_id, UpdateUserRequest(permissions=["users:read", "users:write"]), hr
    )
    assert "users:write" in kept.permissions


def test_cannot_reset_the_password_of_someone_more_powerful(db):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("m1", "manager")
    from app.models.auth_schemas import ResetPasswordRequest

    with pytest.raises(RuleViolation):
        user_controller.reset_password("boss", ResetPasswordRequest(new_password="Valid@1234"), me(db, "m1"))
    with pytest.raises(RuleViolation):
        user_controller.unlock_user("boss", me(db, "m1"))


def test_deactivating_signs_the_user_out_but_changing_ticks_does_not(db):
    db.add_user("boss", ADMIN_ROLE)
    created = user_controller.create_user(
        CreateUserRequest(email="a@x.co", password="Valid@1234", permissions=["stock:read"]), me(db, "boss")
    )
    user_controller.update_user(created.user_id, UpdateUserRequest(permissions=["stock:read", "stock:write"]), me(db, "boss"))
    assert db.revoked == []
    user_controller.update_user(created.user_id, UpdateUserRequest(is_active=False), me(db, "boss"))
    assert db.revoked == [created.user_id]


def test_changing_ticks_takes_effect_on_the_very_next_request(db):
    db.add_user("boss", ADMIN_ROLE)
    created = user_controller.create_user(
        CreateUserRequest(email="a@x.co", password="Valid@1234", permissions=["stock:read"]), me(db, "boss")
    )
    h = auth(created.user_id)
    assert client.post("/stock", json={}, headers=h).status_code == 403
    user_controller.update_user(created.user_id, UpdateUserRequest(permissions=["stock:read", "stock:write"]), me(db, "boss"))
    assert client.post("/stock", json={}, headers=h).status_code == 422  # now past the guard
