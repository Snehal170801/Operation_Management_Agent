"""The Configure tab: an admin changes reminder times and limits; the agents use them straight away."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import access, security, tunables
from app.core.config import settings
from app.core.permissions import ALL_PERMISSIONS, DEPARTMENTS
from app.main import app
from app.repositories import automation_repository, role_repository, user_repository

client = TestClient(app)


@pytest.fixture
def world(monkeypatch):
    stored: dict[str, str] = {}
    audited = []
    users = {u: SimpleNamespace(user_id=u, username=f"{u}@x.co", role=r, is_active=True, email=None, display_name=u) for u, r in
             (("adm", "admin"), ("recv", "dept_delivery"), ("viewer", "viewer"))}
    roles = {f"dept_{d.key}": set(d.permissions) for d in DEPARTMENTS}
    roles.update({"admin": set(ALL_PERMISSIONS), "viewer": {"system:read", "cases:read"}})
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: roles)
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(str(uid).lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    monkeypatch.setattr("app.controllers.config_controller.audit.record", lambda action, **kw: audited.append((action, kw)))
    monkeypatch.setattr(automation_repository, "set_setting", lambda k, v, by: stored.__setitem__(k, v))
    monkeypatch.setattr(automation_repository, "delete_setting", lambda k: stored.pop(k, None))
    monkeypatch.setattr(automation_repository, "list_settings",
                        lambda prefix: [SimpleNamespace(setting_key=k, setting_value=v) for k, v in stored.items() if k.startswith(prefix)])
    access.invalidate()
    return SimpleNamespace(stored=stored, audited=audited)


def head(uid):
    return {"Authorization": f"Bearer {security.create_access_token(uid, f"{uid}@x.co", "x")[0]}"}


def test_everything_listed_exists_and_validates():
    for t in tunables.CATALOG:
        assert hasattr(settings, t.key), t.key
        tunables.validate({t.key: tunables.DEFAULTS[t.key]})  # each default is itself allowed


def test_admin_sees_every_group_with_current_and_default(world):
    body = client.get("/config", headers=head("adm")).json()
    keys = {i["key"] for g in body["groups"] for i in g["items"]}
    assert keys == {t.key for t in tunables.CATALOG}
    item = next(i for g in body["groups"] for i in g["items"] if i["key"] == "RFQ_REMINDER_HOURS")
    assert item["value"] == item["default"] == 24 and item["changed"] is False


def test_changing_a_time_is_saved_applied_and_audited(world):
    r = client.put("/config", json={"values": {"RFQ_REMINDER_HOURS": 6, "APPROVAL_MAX_REMINDERS": "5"}}, headers=head("adm"))
    assert r.status_code == 200
    assert settings.RFQ_REMINDER_HOURS == 6 and settings.APPROVAL_MAX_REMINDERS == 5  # applied now, no restart
    assert world.stored == {"config.RFQ_REMINDER_HOURS": "6", "config.APPROVAL_MAX_REMINDERS": "5"}
    assert {a for a, _ in world.audited} == {"config.change"} and len(world.audited) == 2
    item = next(i for g in r.json()["groups"] for i in g["items"] if i["key"] == "RFQ_REMINDER_HOURS")
    assert item["value"] == 6 and item["changed"] is True


def test_the_agents_really_use_the_new_time(world):
    from datetime import datetime, timedelta
    from app.core.sourcing_policy import next_sourcing_action
    now = datetime(2026, 1, 3, 12)
    rfq = {"rfq_id": "1", "status": "sent", "replied_at": None, "reminder_count": 0, "deadline_at": now + timedelta(days=5),
           "last_contacted_at": now - timedelta(hours=7), "sent_at": now - timedelta(hours=7)}
    assert next_sourcing_action([rfq], 0, now, settings.RFQ_REMINDER_HOURS, settings.RFQ_MAX_REMINDERS)[0] == "wait"
    client.put("/config", json={"values": {"RFQ_REMINDER_HOURS": 6}}, headers=head("adm"))
    assert next_sourcing_action([rfq], 0, now, settings.RFQ_REMINDER_HOURS, settings.RFQ_MAX_REMINDERS)[0] == "remind"


@pytest.mark.parametrize("bad", [{"RFQ_REMINDER_HOURS": 0}, {"RFQ_REMINDER_HOURS": "abc"}, {"RFQ_MAX_REMINDERS": 1.5}, {"RFQ_MAX_REMINDERS": -1},
                                 {"AUTO_APPROVE_MIN_RELIABILITY": 9}, {"CALL_AFTER_EMAIL": "maybe"}, {"JWT_SECRET": "x"}, {"SQL_SERVER": "evil"},
                                 {"RFQ_REMINDER_HOURS": float("nan")}, {"CALL_HOURS_START": 20, "CALL_HOURS_END": 9}])
def test_bad_values_are_refused_and_nothing_changes(world, bad):
    before = {t.key: getattr(settings, t.key) for t in tunables.CATALOG}
    r = client.put("/config", json={"values": {**bad, "LOW_STOCK_AT": 9}} if "nan" not in str(bad) else {"values": {"RFQ_REMINDER_HOURS": "nan"}}, headers=head("adm"))
    assert r.status_code == 422
    assert {t.key: getattr(settings, t.key) for t in tunables.CATALOG} == before and world.stored == {}


def test_putting_back_the_default_removes_the_saved_row(world):
    client.put("/config", json={"values": {"LOW_STOCK_AT": 9}}, headers=head("adm"))
    assert "config.LOW_STOCK_AT" in world.stored
    client.put("/config", json={"values": {"LOW_STOCK_AT": tunables.DEFAULTS["LOW_STOCK_AT"]}}, headers=head("adm"))
    assert world.stored == {}


def test_reset_one_and_reset_all(world):
    client.put("/config", json={"values": {"LOW_STOCK_AT": 9, "DELIVERY_MAX_CHASES": 7}}, headers=head("adm"))
    client.post("/config/reset", json={"keys": ["LOW_STOCK_AT"]}, headers=head("adm"))
    assert settings.LOW_STOCK_AT == tunables.DEFAULTS["LOW_STOCK_AT"] and settings.DELIVERY_MAX_CHASES == 7
    client.post("/config/reset", json={}, headers=head("adm"))
    assert settings.DELIVERY_MAX_CHASES == tunables.DEFAULTS["DELIVERY_MAX_CHASES"] and world.stored == {}


def test_refresh_picks_up_what_another_copy_saved_and_ignores_junk(world):
    world.stored.update({"config.LOW_STOCK_AT": "12", "config.RFQ_MAX_REMINDERS": "not a number", "config.NOT_A_SETTING": "1"})
    tunables.refresh()
    assert settings.LOW_STOCK_AT == 12 and settings.RFQ_MAX_REMINDERS == tunables.DEFAULTS["RFQ_MAX_REMINDERS"]
    assert not hasattr(settings, "NOT_A_SETTING")


def test_only_people_with_the_right_permission(world):
    assert client.get("/config", headers=head("viewer")).status_code == 200          # may look
    assert client.put("/config", json={"values": {"LOW_STOCK_AT": 9}}, headers=head("viewer")).status_code == 403
    assert client.post("/config/reset", json={}, headers=head("recv")).status_code == 403
    assert client.get("/config", headers=head("recv")).status_code == 403
    assert client.get("/config").status_code == 401
    assert world.stored == {}
