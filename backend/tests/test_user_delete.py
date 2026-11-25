"""Deleting users, and activating / deactivating them. Reuses the in-memory fakes from test_rbac."""

import pytest
from fastapi.testclient import TestClient

from app.controllers import user_controller
from app.core.exceptions import RuleViolation, UserNotFound
from app.core.permissions import ADMIN_ROLE
from app.main import app
from app.models.auth_schemas import UpdateUserRequest
from app.repositories import user_repository

from .test_rbac import auth, db, me  # noqa: F401  (db is a fixture)

client = TestClient(app)


@pytest.fixture
def deleted(db, monkeypatch):
    gone = []
    monkeypatch.setattr(user_repository, "delete_user", lambda uid: gone.append(uid) or db.users.pop(uid.lower(), None))
    return gone


def test_an_admin_can_delete_a_user_and_it_is_audited(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("v1", "viewer")
    user_controller.delete_user("v1", me(db, "boss"))
    assert deleted == ["v1"] and "v1" not in db.users
    assert "v1" in db.revoked                                   # signed out everywhere first
    action, detail = db.audit[-1]
    assert action == "user.delete" and detail["detail"]["user"] == "v1@x.co" and detail["actor_username"] == "boss@x.co"


def test_you_cannot_delete_yourself(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("boss2", ADMIN_ROLE)
    with pytest.raises(RuleViolation, match="own account"):
        user_controller.delete_user("boss", me(db, "boss"))
    assert deleted == []


def test_the_last_active_admin_cannot_be_deleted(db, deleted):
    db.add_user("ghost", ADMIN_ROLE, active=False)
    db.add_user("only", ADMIN_ROLE)
    with pytest.raises(RuleViolation, match="at least one active admin"):
        user_controller.delete_user("only", me(db, "ghost"))
    assert deleted == []


def test_an_inactive_admin_can_be_deleted_while_another_admin_remains(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("old", ADMIN_ROLE, active=False)
    user_controller.delete_user("old", me(db, "boss"))
    assert deleted == ["old"]


def test_someone_cannot_delete_a_user_with_more_access_than_themselves(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("m1", "manager")
    with pytest.raises(RuleViolation, match="more access"):
        user_controller.delete_user("boss", me(db, "m1"))
    assert deleted == []


def test_deleting_someone_who_does_not_exist_is_a_clean_error(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    with pytest.raises(UserNotFound):
        user_controller.delete_user("nobody", me(db, "boss"))


def test_a_deleted_users_own_checkmark_set_is_removed_with_them(db, deleted):
    from app.core.permissions import private_role_name
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("v1", private_role_name("v1"))
    db.roles[private_role_name("v1")] = {"stock:read"}
    user_controller.delete_user("v1", me(db, "boss"))
    assert private_role_name("v1") not in db.roles and "viewer" in db.roles   # shared sets are never touched


def test_deleting_a_user_from_a_shared_role_leaves_the_role_alone(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("v1", "viewer")
    user_controller.delete_user("v1", me(db, "boss"))
    assert "viewer" in db.roles


# ---------- activate / deactivate (the existing update path) ----------

def test_deactivate_then_activate_round_trips_and_deactivation_ends_sessions(db):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("v1", "viewer")
    off = user_controller.update_user("v1", UpdateUserRequest(is_active=False), me(db, "boss"))
    assert off.is_active is False and "v1" in db.revoked
    on = user_controller.update_user("v1", UpdateUserRequest(is_active=True), me(db, "boss"))
    assert on.is_active is True


def test_the_last_active_admin_cannot_be_deactivated(db):
    db.add_user("ghost", ADMIN_ROLE, active=False)
    db.add_user("only", ADMIN_ROLE)
    with pytest.raises(RuleViolation, match="at least one active admin"):
        user_controller.update_user("only", UpdateUserRequest(is_active=False), me(db, "ghost"))


# ---------- over HTTP ----------

def test_deleting_needs_a_login():
    assert client.delete("/users/abc").status_code == 401


def test_deleting_needs_the_manage_users_permission(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("v1", "viewer")
    token = auth("v1")
    # the helper in test_rbac signs a token whose role is ignored: the server re-reads the real role
    assert client.delete("/users/boss", headers=token).status_code == 403
    assert deleted == []


def test_an_admin_deletes_over_http(db, deleted):
    db.add_user("boss", ADMIN_ROLE)
    db.add_user("v1", "viewer")
    assert client.delete("/users/v1", headers=auth("boss")).status_code == 204 and deleted == ["v1"]
    assert client.delete("/users/boss", headers=auth("boss")).status_code == 409      # not yourself
