"""'Who else has this case open?': a check-in list that forgets people who go away."""

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core import presence
from app.main import app
from app.models.auth_schemas import CurrentUser

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    presence.reset()
    yield
    presence.reset()
    app.dependency_overrides.clear()


def test_you_never_see_yourself_only_the_others():
    assert presence.checkin("c1", "alice@x.co", now=100) == []
    assert presence.checkin("c1", "bob@x.co", now=101) == ["alice@x.co"]
    assert presence.checkin("c1", "alice@x.co", now=102) == ["bob@x.co"]


def test_names_are_matched_without_regard_to_case_and_each_case_is_separate():
    presence.checkin("C1", "Alice@x.co", now=100)
    assert presence.checkin("c1", "alice@X.co", now=101) == []          # same person, same case
    assert presence.checkin("c2", "bob@x.co", now=101) == []            # another case: nobody there


def test_someone_who_stops_checking_in_disappears_after_the_timeout():
    presence.checkin("c1", "alice@x.co", now=100)
    assert presence.checkin("c1", "bob@x.co", now=100 + presence.TTL - 1) == ["alice@x.co"]
    assert presence.checkin("c1", "bob@x.co", now=100 + presence.TTL + 5) == []


def test_leaving_removes_you_straight_away():
    presence.checkin("c1", "alice@x.co", now=100)
    presence.leave("c1", "Alice@x.co")
    assert presence.checkin("c1", "bob@x.co", now=101) == []
    presence.leave("nowhere", "ghost")        # leaving a case you were never on is harmless


def test_the_list_cannot_grow_without_limit(monkeypatch):
    monkeypatch.setattr(presence, "MAX_CASES", 3)
    for i in range(10):
        presence.checkin(f"c{i}", "a@x.co", now=100 + i * (presence.TTL + 1))   # each earlier one has expired by the next
    assert len(presence._seen) <= 4


def as_user(username, role):
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="1", username=username, role=role)


def test_staff_check_in_over_the_api_and_see_each_other():
    as_user("alice@x.co", "admin")
    assert client.post("/presence/cases/c1").json() == {"others": []}
    as_user("bob@x.co", "admin")
    assert client.post("/presence/cases/c1").json() == {"others": ["alice@x.co"]}
    assert client.delete("/presence/cases/c1").status_code == 204
    as_user("alice@x.co", "admin")
    assert client.post("/presence/cases/c1").json() == {"others": []}


def test_a_requester_cannot_use_it_and_nobody_signed_out_can_either(monkeypatch):
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: role == "admin")   # no database here
    as_user("req@x.co", "user")
    assert client.post("/presence/cases/c1").status_code == 403
    app.dependency_overrides.clear()
    assert client.post("/presence/cases/c1").status_code == 401
