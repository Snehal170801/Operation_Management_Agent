import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.exceptions import InvalidToken, WeakPassword
from app.main import app

client = TestClient(app)


def test_password_hash_roundtrip():
    hashed = security.hash_password("Sup3rSecret")
    assert hashed != "Sup3rSecret"
    assert security.verify_password("Sup3rSecret", hashed)
    assert not security.verify_password("wrong", hashed)


def test_overlong_password_is_rejected_not_truncated():
    assert not security.verify_password("a" * 100, security.hash_password("a" * 72))


def test_access_token_roundtrip_and_tamper_detection():
    token, _ = security.create_access_token("u1", "alice", "manager")
    payload = security.decode_access_token(token)
    assert payload["sub"] == "u1" and payload["role"] == "manager"
    head, body, signature = token.split(".")
    # change the FIRST signature character: every bit of it counts, unlike the last one, which can carry unused bits
    tampered = ".".join([head, body, ("A" if signature[0] != "A" else "B") + signature[1:]])
    with pytest.raises(InvalidToken):
        security.decode_access_token(tampered)


@pytest.mark.parametrize("password", ["short", "alllowercase1", "ALLUPPERCASE1", "NoNumbersHere"])
def test_weak_passwords_rejected(password):
    with pytest.raises(WeakPassword):
        security.validate_password_strength(password)


def test_password_may_not_contain_username():
    with pytest.raises(WeakPassword):
        security.validate_password_strength("Alice12345", "alice")


@pytest.mark.parametrize("path", ["/cases", "/stock", "/vendors", "/approvals", "/users", "/users/permissions", "/audit", "/system/health", "/auth/me"])
def test_protected_routes_need_a_token(path):
    assert client.get(path).status_code == 401


def test_garbage_token_is_rejected():
    assert client.get("/cases", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
