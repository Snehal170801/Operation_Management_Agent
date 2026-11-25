"""What happens when things go wrong: the database drops, the mail server refuses, the AI times out or rambles, a route crashes.

Each test breaks one thing on purpose and checks that the person or the next step gets a clean, honest result."""

import smtplib
from types import SimpleNamespace

import pyodbc
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.clients import azure_openai_client, email_client
from app.core import retry as retry_module
from app.core.retry import retry
from app.db import connection
from app.main import app

NO_WAIT = lambda seconds: None  # noqa: E731


# ---- the retry helper -----------------------------------------------------------------------------------------------------

def test_a_passing_failure_is_retried_until_it_works():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("blip")
        return "ok"

    assert retry(flaky, attempts=3, transient=lambda e: True, sleep=NO_WAIT) == "ok" and len(calls) == 3


def test_the_last_failure_is_raised_unchanged_after_the_attempts_run_out():
    def always():
        raise ConnectionError("still down")

    with pytest.raises(ConnectionError, match="still down"):
        retry(always, attempts=2, transient=lambda e: True, sleep=NO_WAIT)


def test_a_failure_that_cannot_pass_is_not_retried_at_all():
    calls = []

    def refused():
        calls.append(1)
        raise PermissionError("no")

    with pytest.raises(PermissionError):
        retry(refused, attempts=5, transient=lambda e: isinstance(e, ConnectionError), sleep=NO_WAIT)
    assert len(calls) == 1


def test_the_wait_grows_between_tries():
    waits = []

    def always():
        raise ConnectionError("x")

    with pytest.raises(ConnectionError):
        retry(always, attempts=4, delay=1.0, backoff=2.0, transient=lambda e: True, sleep=waits.append)
    assert waits == [1.0, 2.0, 4.0]


# ---- the database ---------------------------------------------------------------------------------------------------------

def test_which_database_errors_count_as_passing():
    assert connection.is_connection_problem(pyodbc.OperationalError("08001", "Client unable to establish connection"))
    assert connection.is_connection_problem(pyodbc.OperationalError("HYT00", "Login timeout expired"))
    assert connection.is_connection_problem(pyodbc.Error("08S01", "Communication link failure"))
    assert not connection.is_connection_problem(pyodbc.InterfaceError("28000", "Login failed for user"))      # wrong login: retrying cannot help
    assert not connection.is_connection_problem(pyodbc.InterfaceError("IM002", "Data source name not found"))   # no driver
    assert not connection.is_connection_problem(pyodbc.ProgrammingError("42S22", "Invalid column name"))        # a bug, not an outage
    assert not connection.is_connection_problem(ValueError("x"))


def test_a_database_that_blips_is_connected_to_on_the_second_try(monkeypatch):
    attempts = []

    def connect(*a, **k):
        attempts.append(1)
        if len(attempts) == 1:
            raise pyodbc.OperationalError("08001", "Client unable to establish connection")
        return SimpleNamespace(timeout=0)

    monkeypatch.setattr(connection.pyodbc, "connect", connect)
    monkeypatch.setattr(retry_module.time, "sleep", NO_WAIT)
    assert connection.get_connection() is not None and len(attempts) == 2


def test_a_wrong_login_fails_at_once_without_hammering_the_server(monkeypatch):
    attempts = []

    def connect(*a, **k):
        attempts.append(1)
        raise pyodbc.InterfaceError("28000", "Login failed for user 'x'")

    monkeypatch.setattr(connection.pyodbc, "connect", connect)
    with pytest.raises(pyodbc.InterfaceError):
        connection.get_connection()
    assert len(attempts) == 1


# ---- email ----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def smtp(monkeypatch):
    sent = SimpleNamespace(tries=0, plan=[])
    monkeypatch.setattr(email_client.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_client.settings, "SMTP_USER", "u")
    monkeypatch.setattr(email_client.settings, "SMTP_PASSWORD", "p")
    monkeypatch.setattr(retry_module.time, "sleep", NO_WAIT)

    class FakeSMTP:
        def __init__(self, *a, **k):
            sent.tries += 1
            if sent.plan and sent.plan[0] == "connect":
                sent.plan.pop(0)
                raise smtplib.SMTPConnectError(421, "busy")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            if sent.plan and sent.plan[0] == "auth":
                raise smtplib.SMTPAuthenticationError(535, b"bad password")

        def send_message(self, message):
            if sent.plan and sent.plan[0] == "refused":
                raise smtplib.SMTPRecipientsRefused({"x@y.z": (550, b"no such user")})

    monkeypatch.setattr(email_client.smtplib, "SMTP", FakeSMTP)
    return sent


def test_a_busy_mail_server_is_tried_again_and_the_mail_still_goes(smtp):
    smtp.plan = ["connect"]
    email_client.send_email("a@x.co", "s", "b")
    assert smtp.tries == 2


def test_a_wrong_mail_password_is_not_retried(smtp):
    smtp.plan = ["auth"]
    with pytest.raises(smtplib.SMTPAuthenticationError):
        email_client.send_email("a@x.co", "s", "b")
    assert smtp.tries == 1


def test_a_refused_address_is_not_retried_and_is_reported(smtp):
    smtp.plan = ["refused"]
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        email_client.send_email("a@x.co", "s", "b")
    assert smtp.tries == 1


# ---- the AI ---------------------------------------------------------------------------------------------------------------

def reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def fake_ai(monkeypatch, answers):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        answer = answers[min(len(calls) - 1, len(answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return reply(answer)

    monkeypatch.setattr(azure_openai_client._client.chat.completions, "create", create)
    return calls


def test_the_ai_client_has_a_time_limit_instead_of_waiting_ten_minutes():
    assert azure_openai_client.TIMEOUT_SECONDS == 60
    assert azure_openai_client._client.timeout == 60


def test_a_good_answer_is_used_straight_away(monkeypatch):
    calls = fake_ai(monkeypatch, ['{"a": 1}'])
    assert azure_openai_client.ask_json("s", "u") == {"a": 1} and len(calls) == 1


@pytest.mark.parametrize("bad", ["", "not json", '{"cut": ', "[1, 2]", None])
def test_an_unusable_answer_is_asked_for_once_more(monkeypatch, bad):
    calls = fake_ai(monkeypatch, [bad, '{"ok": true}'])
    assert azure_openai_client.ask_json("s", "u") == {"ok": True} and len(calls) == 2


def test_two_unusable_answers_in_a_row_give_a_clear_error_not_a_crash_inside_the_agent(monkeypatch):
    calls = fake_ai(monkeypatch, ["nonsense"])
    with pytest.raises(ValueError, match="did not return a usable answer"):
        azure_openai_client.ask_json("s", "u")
    assert len(calls) == 2


def test_an_ai_outage_still_reaches_the_caller_as_an_error_it_already_handles(monkeypatch):
    fake_ai(monkeypatch, [TimeoutError("timed out")])
    with pytest.raises(TimeoutError):
        azure_openai_client.ask_json("s", "u")


# ---- a route that crashes -------------------------------------------------------------------------------------------------

boom = APIRouter()


@boom.get("/_test/crash")
def crash():
    raise RuntimeError("secret detail: password=hunter2 at C:\\inner\\path")


@boom.get("/_test/db-down")
def db_down():
    raise pyodbc.OperationalError("08001", "Client unable to establish connection")


@boom.get("/_test/fine")
def fine():
    return {"ok": True}


app.include_router(boom)
client = TestClient(app, raise_server_exceptions=False)


def test_an_unplanned_error_is_a_clean_json_500_with_a_reference_and_no_internals():
    r = client.get("/_test/crash")
    body = r.json()
    assert r.status_code == 500 and r.headers["content-type"].startswith("application/json")
    assert body["request_id"] == r.headers["x-request-id"] and len(body["request_id"]) == 8
    assert "hunter2" not in r.text and "inner" not in r.text and "RuntimeError" not in r.text
    assert "Something went wrong" in body["detail"]


def test_the_reference_is_in_the_log_so_support_can_find_it(caplog):
    with caplog.at_level("ERROR", logger="app.errors"):
        rid = client.get("/_test/crash").json()["request_id"]
    assert any(rid in rec.getMessage() and "/_test/crash" in rec.getMessage() for rec in caplog.records)


def test_a_database_outage_says_so_and_asks_to_try_again_with_503():
    r = client.get("/_test/db-down")
    assert r.status_code == 503 and "database is not reachable" in r.json()["detail"] and "08001" not in r.text


def test_the_error_answer_carries_the_cors_headers_so_the_browser_can_read_it():
    r = client.get("/_test/crash", headers={"Origin": "http://localhost:5180"})
    assert r.status_code == 500 and r.headers.get("access-control-allow-origin") == "http://localhost:5180"


def test_every_answer_carries_a_reference_and_a_caller_supplied_one_is_kept_when_it_is_safe():
    assert len(client.get("/_test/fine").headers["x-request-id"]) == 8
    assert client.get("/_test/fine", headers={"X-Request-ID": "abc123"}).headers["x-request-id"] == "abc123"
    assert client.get("/_test/fine", headers={"X-Request-ID": "bad id\r\n<script>"}).headers["x-request-id"] != "bad id\r\n<script>"


def test_planned_errors_are_unchanged():
    assert client.get("/_test/does-not-exist").status_code == 404
