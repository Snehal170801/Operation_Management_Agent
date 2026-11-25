"""scripts/create_user.py: --role must decide the stored role (it once read a flag that did not exist)."""

import sys

import pytest

from scripts import create_user


@pytest.fixture
def saved(monkeypatch):
    calls = []
    monkeypatch.setattr(create_user.user_repository, "upsert_user", lambda **kw: calls.append(kw) or True)
    monkeypatch.setattr(create_user, "hash_password", lambda p: "hashed")
    return calls


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["create_user", *argv])
    return create_user.main()


def test_role_admin_creates_an_admin(monkeypatch, saved, capsys):
    assert run(monkeypatch, "Boss@Example.com", "--role", "admin", "--password", "Str0ng-Passw0rd!x") == 0
    assert saved[0]["role"] == "admin" and saved[0]["username"] == "boss@example.com"
    assert "admin 'Boss@Example.com'" in capsys.readouterr().out


def test_default_role_is_user(monkeypatch, saved):
    assert run(monkeypatch, "a@example.com", "--password", "Str0ng-Passw0rd!x") == 0
    assert saved[0]["role"] == "user"


def test_a_weak_password_creates_nothing(monkeypatch, saved):
    assert run(monkeypatch, "a@example.com", "--password", "abc") == 1
    assert saved == []


def test_an_unknown_role_is_refused(monkeypatch, saved):
    with pytest.raises(SystemExit):
        run(monkeypatch, "a@example.com", "--role", "root", "--password", "Str0ng-Passw0rd!x")
    assert saved == []
