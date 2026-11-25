"""A case with no order yet is answered with an empty 200, not a 404 (so the browser console stays clean); an unknown case is still 404 and
staff-only access is unchanged."""

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.models.auth_schemas import CurrentUser

from .fake_world import standard_world
from .test_restock import ADMIN, ordered_reorder, w  # noqa: F401 (the fixture)

client = TestClient(app, raise_server_exceptions=False)
UNKNOWN = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def staff(monkeypatch, w):  # noqa: F811
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: role in ("admin", "u_stores"))
    app.dependency_overrides[deps.get_current_user] = lambda: ADMIN
    yield
    app.dependency_overrides.clear()


def test_a_case_without_an_order_gets_an_empty_answer_for_the_order_and_the_delivery(staff, w):  # noqa: F811
    w.teach("2 laptops please", [{"description": "Laptop", "quantity": 2}])
    case_id = w.submit("2 laptops please")
    for path in ("purchase-order", "delivery"):
        answer = client.get(f"/cases/{case_id}/{path}")
        assert answer.status_code == 200 and answer.json() is None, path


def test_a_case_that_does_not_exist_is_still_not_found(staff, w):  # noqa: F811
    assert client.get(f"/cases/{UNKNOWN}/purchase-order").status_code == 404
    assert client.get(f"/cases/{UNKNOWN}/delivery").status_code == 404


def test_once_the_order_exists_both_are_returned_as_before(staff, w):  # noqa: F811
    case_id = ordered_reorder(w)
    po = client.get(f"/cases/{case_id}/purchase-order").json()
    assert po["po_number"].startswith("PO-") and client.get(f"/cases/{case_id}/delivery").json()["po_number"] == po["po_number"]


def test_people_without_view_all_still_cannot_read_them_and_signed_out_gets_401(monkeypatch, w):  # noqa: F811
    case_id = ordered_reorder(w)
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: False)
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="req", role="u_requester")
    try:
        assert client.get(f"/cases/{case_id}/purchase-order").status_code == 403
        assert client.get(f"/cases/{case_id}/delivery").status_code == 403
    finally:
        app.dependency_overrides.clear()
    assert client.get(f"/cases/{case_id}/purchase-order").status_code == 401
