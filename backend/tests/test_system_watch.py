"""The system watching itself: a background job that goes quiet is noticed, and an admin is told once."""

from types import SimpleNamespace

import pytest

from app.agents import notification_agent
from app.controllers import notification_controller, system_controller
from app.core import heartbeat, system_watch
from app.core.heartbeat import Beat, assess
from app.core.system_watch import Watch
from app.repositories import system_repository

T0 = 1_000_000.0          # an arbitrary "app started" moment
INTERVAL = 60
BOTH = {heartbeat.WORKER, heartbeat.MAILBOX}


def verdicts(now, beats, expected=BOTH, started=T0):
    return {c.key: c for c in assess(now, beats, started=started, interval_seconds=INTERVAL, expected=expected)}


@pytest.fixture(autouse=True)
def clean():
    heartbeat.reset()
    system_watch.watch.reset()
    yield
    heartbeat.reset()
    system_watch.watch.reset()


# ---- the verdicts ------------------------------------------------------------------------------------------------------

def test_a_loop_nobody_expects_is_never_judged():
    assert assess(T0 + 9999, {}, started=T0, interval_seconds=INTERVAL, expected=set()) == []      # tests, or a disabled worker


def test_right_after_a_start_nothing_is_blamed():
    v = verdicts(T0 + 30, {})
    assert v["worker"].status == "ok" and v["mailbox"].status == "ok"


def test_a_worker_that_never_ran_is_down_once_the_start_up_time_has_passed():
    v = verdicts(T0 + 500, {})
    assert v["worker"].status == "down" and "has not run since the app started" in v["worker"].detail


def test_a_worker_is_ok_while_it_keeps_going_round_and_slow_ticks_are_forgiven():
    assert verdicts(T0 + 500, {"worker": Beat(at=T0 + 490)})["worker"].status == "ok"
    assert verdicts(T0 + 500, {"worker": Beat(at=T0 + 340)})["worker"].status == "ok"       # 160 s quiet: a slow tick, not a stop


def test_a_quiet_worker_is_a_warning_then_down():
    assert verdicts(T0 + 1000, {"worker": Beat(at=T0 + 700)})["worker"].status == "warning"     # 5 min
    down = verdicts(T0 + 2000, {"worker": Beat(at=T0 + 500)})["worker"]                           # 25 min
    assert down.status == "down" and "25 min" in down.detail


def test_the_mailbox_watcher_is_ok_while_it_is_renewing_itself():
    assert verdicts(T0 + 2000, {"mailbox": Beat(at=T0 + 1500), "worker": Beat(at=T0 + 1990)})["mailbox"].status == "ok"


def test_the_mailbox_watcher_warns_on_one_failure_and_is_down_after_three_in_a_row():
    one = verdicts(T0 + 700, {"mailbox": Beat(at=T0 + 600, failures=1, last_error="login failed")})["mailbox"]
    three = verdicts(T0 + 700, {"mailbox": Beat(at=T0 + 600, failures=3, last_error="login failed")})["mailbox"]
    assert one.status == "warning" and "login failed" in one.detail
    assert three.status == "down" and "3 tries" in three.detail


def test_a_mailbox_watcher_that_never_connected_is_down_after_start_up():
    assert verdicts(T0 + 700, {})["mailbox"].status == "down"
    failing = verdicts(T0 + 700, {"mailbox": Beat(at=0, failures=4, last_error="timed out")})["mailbox"]
    assert failing.status == "down" and "timed out" in failing.detail


def test_beat_and_fail_record_what_the_loops_do():
    heartbeat.beat("mailbox", now=T0)
    heartbeat.fail("mailbox", RuntimeError("boom\nsecond line"))
    heartbeat.fail("mailbox", RuntimeError("boom again"))
    b = heartbeat.snapshot()["mailbox"]
    assert b.at == T0 and b.failures == 2 and b.last_error == "boom again"          # the good beat is kept, one line of the error
    heartbeat.beat("mailbox", now=T0 + 5)
    assert heartbeat.snapshot()["mailbox"].failures == 0                              # a good round clears the failures


# ---- telling the admin once ---------------------------------------------------------------------------------------------

def check(status, key="worker"):
    return heartbeat.Check(key, "Background worker", status, "x")


def test_a_problem_is_announced_only_after_it_shows_twice_in_a_row_and_only_once():
    w = Watch()
    assert w.step([check("down")], 100) == []                         # first sighting: could be a blip
    events = w.step([check("down")], 160)
    assert [e.kind for e in events] == ["down"] and events[0].since == 100
    assert w.step([check("down")], 220) == []                         # still down: not repeated


def test_a_blip_that_clears_is_never_announced():
    w = Watch()
    assert w.step([check("warning")], 100) == []
    assert w.step([check("ok")], 160) == []
    assert w.step([check("warning")], 220) == []                      # the count started again


def test_recovery_is_announced_once_and_only_if_the_problem_was():
    w = Watch()
    w.step([check("down")], 100)
    w.step([check("down")], 160)
    assert [e.kind for e in w.step([check("ok")], 220)] == ["recovered"]
    assert w.step([check("ok")], 280) == []
    assert Watch().step([check("ok")], 1) == []


def test_each_job_is_tracked_separately():
    w = Watch()
    w.step([check("down", "worker"), check("ok", "mailbox")], 100)
    events = w.step([check("down", "worker"), check("down", "mailbox")], 160)
    assert [e.check.key for e in events] == ["worker"]


# ---- the email, the health page and the bell ---------------------------------------------------------------------------

def stub_mail(monkeypatch, emails):
    sent = []
    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission",
                        lambda permission: [SimpleNamespace(email=e) for e in emails])
    monkeypatch.setattr(notification_agent.email_client, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def test_admins_with_an_email_are_told_what_stopped_and_what_to_do(monkeypatch):
    sent = stub_mail(monkeypatch, ["a@x.co", None, "b@x.co"])
    assert notification_agent.notify_system("down", "Background worker", "It has not run for 25 min.", "05 Oct 12:00") == 2
    assert [m[0] for m in sent] == ["a@x.co", "b@x.co"]
    subject, body = sent[0][1], sent[0][2]
    assert subject == "ALERT: Background worker needs attention"
    assert "25 min" in body and "05 Oct 12:00" in body and "restart" in body.lower()


def test_recovery_email_says_it_is_fine_now(monkeypatch):
    sent = stub_mail(monkeypatch, ["a@x.co"])
    notification_agent.notify_system("recovered", "Background worker", "", "05 Oct 12:00")
    assert sent[0][1] == "Recovered: Background worker is working again" and "Nothing more is needed" in sent[0][2]


def test_a_failing_email_does_not_stop_the_others(monkeypatch):
    sent = []

    def flaky(to, subject, body):
        if to == "a@x.co":
            raise RuntimeError("smtp down")
        sent.append(to)

    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission",
                        lambda p: [SimpleNamespace(email="a@x.co"), SimpleNamespace(email="b@x.co")])
    monkeypatch.setattr(notification_agent.email_client, "send_email", flaky)
    assert notification_agent.notify_system("down", "Background worker", "x", "now") == 1 and sent == ["b@x.co"]


def test_the_health_page_lists_the_background_jobs(monkeypatch):
    monkeypatch.setattr(system_repository, "get_db_overview", lambda: {
        "server_version": "x", "users": 1, "active_sessions": 0, "cases": 0, "open_cases": 0, "migrations_applied": 1})
    assert "Background worker" not in {c.name for c in system_controller.get_health().checks}      # nobody expects it in a test
    heartbeat.expect(heartbeat.WORKER)
    monkeypatch.setattr(heartbeat, "STARTED", 0.0)       # long ago, so the start-up allowance is over
    health = system_controller.get_health()
    worker = next(c for c in health.checks if c.name == "Background worker")
    assert worker.status == "down" and health.status == "down"
    heartbeat.beat(heartbeat.WORKER)
    assert next(c for c in system_controller.get_health().checks if c.name == "Background worker").status == "ok"


def test_only_admins_see_a_stopped_job_in_the_bell(monkeypatch):
    heartbeat.expect(heartbeat.WORKER)
    monkeypatch.setattr(heartbeat, "STARTED", 0.0)
    monkeypatch.setattr(notification_controller.approval_agent, "get_approvals", lambda **k: [])
    monkeypatch.setattr(notification_controller.operations_agent, "get_all_cases", lambda *_: [])
    monkeypatch.setattr(notification_controller.invoice_agent, "list_invoices", lambda *_: [])
    monkeypatch.setattr(notification_controller.case_access, "can_view_all", lambda user: True)
    monkeypatch.setattr(notification_controller.access, "has_permission", lambda role, permission: role == "admin" or permission != "system:write")
    admin = notification_controller.list_notifications(SimpleNamespace(role="admin", username="a"))
    other = notification_controller.list_notifications(SimpleNamespace(role="vendor", username="v"))
    assert [n.id for n in admin] == ["system:worker"] and admin[0].requires_action and "needs attention" in admin[0].title
    assert other == []


# ---- the stand-alone watchdog (for when the whole server is down) -------------------------------------------------------

def test_the_watchdog_speaks_after_three_failures_once_and_again_on_recovery():
    from scripts.watchdog import Tracker

    t = Tracker()
    assert [t.step(False, n) for n in (1, 2)] == [None, None]
    assert t.step(False, 3) == "down" and t.down_since == 1
    assert t.step(False, 4) is None                      # not repeated while it stays down
    assert t.step(True, 5) == "recovered"
    assert t.step(True, 6) is None
    assert t.step(False, 7) is None                      # a fresh outage starts counting from scratch


def test_one_missed_check_is_never_announced():
    from scripts.watchdog import Tracker

    t = Tracker()
    assert [t.step(up, n) for n, up in enumerate([False, True, False, True, False, False, True])] == [None] * 7


def test_the_watchdog_checks_a_url_and_writes_sensible_emails(monkeypatch):
    from scripts import watchdog

    assert watchdog.is_up("http://127.0.0.1:1/health", timeout=1) is False          # nothing listening there
    monkeypatch.setenv("WATCHDOG_ALERT_TO", "a@x.co, b@x.co")
    assert watchdog.recipients(None) == ["a@x.co", "b@x.co"] and watchdog.recipients("c@x.co") == ["c@x.co"]
    subject, body = watchdog.message("down", "http://h/health", 0)
    assert "DOWN" in subject and "http://h/health" in body and "uvicorn" in body
    assert "back" in watchdog.message("recovered", "http://h/health", 0)[0]
