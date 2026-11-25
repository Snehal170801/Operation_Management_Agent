import re

import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.exceptions import WeakPassword
from app.main import app

client = TestClient(app)


def test_otp_is_six_digits():
    for _ in range(200):
        assert re.fullmatch(r"\d{6}", security.generate_otp())


def test_otp_hash_is_bound_to_the_user_and_code():
    a = security.hash_otp("USER-1", "123456")
    assert a == security.hash_otp("user-1", "123456")  # user id is case-insensitive
    assert a != security.hash_otp("user-2", "123456")
    assert a != security.hash_otp("user-1", "123457")
    assert "123456" not in a


def test_password_may_not_contain_the_email_name():
    with pytest.raises(WeakPassword):
        security.validate_password_strength("Snehalc@2026", "snehalc@daccess.co")
    security.validate_password_strength("Admin@123", "snehalc@daccess.co")  # fine


@pytest.mark.parametrize("otp", ["12345", "1234567", "abcdef", "12 456", ""])
def test_confirm_rejects_malformed_codes_before_touching_the_db(otp):
    res = client.post(
        "/auth/forgot-password/confirm",
        json={"identifier": "a@b.co", "otp": otp, "new_password": "Whatever1"},
    )
    assert res.status_code == 422


def test_forgot_password_requires_an_identifier():
    assert client.post("/auth/forgot-password", json={"identifier": ""}).status_code == 422


def test_create_user_requires_a_valid_email(monkeypatch):
    from app.core import access

    monkeypatch.setattr(access, "get_user_state", lambda uid: access.UserState(uid, "admin@x.co", "admin", True))
    token, _ = security.create_access_token("admin-id", "admin@x.co", "admin")
    res = client.post(
        "/users",
        json={"email": "not-an-email", "password": "Valid@1234", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
