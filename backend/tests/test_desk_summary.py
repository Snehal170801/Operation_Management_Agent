"""The morning summary e-mail to each department: when it is due, who gets it, and that quiet days stay quiet."""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.core import desk_summary as rules, tunables
from app.core.config import settings
from app.models.my_work_schemas import MyWork
from app.orchestrator import desk_summary

# 09:00 India time is 03:30 UTC
NINE_IST = datetime(2026, 10, 6, 3, 30)


# ---- when ---------------------------------------------------------------------------------------------------------------------------

def test_it_is_due_from_the_set_hour_for_a_few_hours_and_only_once_a_day():
    assert rules.is_due(NINE_IST, True, 9, None)
    assert rules.is_due(datetime(2026, 10, 6, 3, 0), True, 9, None) is False                 # 08:30 IST: too early
    assert rules.is_due(datetime(2026, 10, 6, 8, 0), True, 9, None) is True                  # 13:30 IST: 4.5h late, still the same morning's catch-up
    assert rules.is_due(datetime(2026, 10, 6, 9, 30), True, 9, None) is False                # 15:00 IST: too late for a morning e-mail
    assert rules.is_due(NINE_IST, True, 9, date(2026, 10, 6)) is False                       # already sent today
    assert rules.is_due(NINE_IST, True, 9, date(2026, 10, 5)) is True
    assert rules.is_due(NINE_IST, False, 9, None) is False                                   # switched off


def test_the_india_date_decides_the_day_not_utc():
    assert rules.today_ist(datetime(2026, 10, 5, 20, 0)) == date(2026, 10, 6)                # 01:30 IST next morning


# ---- what ---------------------------------------------------------------------------------------------------------------------------

def item(title, urgent=False, detail="why"):
    return {"title": title, "detail": detail, "urgent": urgent}


def work(*queues):
    return {"total": sum(len(q) for q in queues), "queues": [{"title": "Queue", "items": q} for q in queues]}


def test_nothing_waiting_means_no_e_mail():
    assert rules.body("Accounts", work([]), "http://x") is None
    assert rules.body("Accounts", {"total": 0, "queues": []}, "http://x") is None


def test_the_e_mail_is_short_marks_urgent_work_and_links_to_the_app():
    many = [item(f"Order {i}", urgent=(i == 0)) for i in range(8)]
    text = rules.body("Approvers", work(many), "http://app")
    assert "URGENT: Order 0" in text and "... and 3 more" in text and "Order 7" not in text and "http://app/my-work" in text
    assert rules.subject("Approvers", 8, rules.urgent_count(work(many))) == "Approvers: 8 waiting for you today (1 urgent)"
    assert rules.subject("Accounts", 2, 0) == "Accounts: 2 waiting for you today"


# ---- sending ------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def mail(monkeypatch):
    sent, saved = [], {}
    people = {"approvals:write": [SimpleNamespace(email="a@x.co", role="u_a"), SimpleNamespace(email="boss@x.co", role="admin")],
              "invoices:decide": [SimpleNamespace(email="acc@x.co", role="u_acc")], "po:manage": [SimpleNamespace(email=None, role="u_po")]}
    monkeypatch.setattr(desk_summary.user_repository, "find_active_users_with_permission", lambda p: people.get(p, []))
    monkeypatch.setattr(desk_summary.automation_repository, "get_setting", lambda k: SimpleNamespace(setting_value=saved[k]) if k in saved else None)
    monkeypatch.setattr(desk_summary.automation_repository, "set_setting", lambda k, v, by: saved.__setitem__(k, v))

    def claim(k, v, by):                                   # (the real one is a single atomic statement)
        if saved.get(k) == v:
            return False
        saved[k] = v
        return True
    monkeypatch.setattr(desk_summary.automation_repository, "claim_setting", claim)
    monkeypatch.setattr(desk_summary.email_client, "send_email", lambda to, subject, body, html=None: sent.append((to, subject, body)))
    monkeypatch.setattr(settings, "DESK_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "DESK_SUMMARY_HOUR", 9)

    def waiting(username, can):
        queues = []
        if can("approvals:write"):
            queues.append({"key": "approval", "title": "Orders waiting", "agent": "A", "empty": "", "items": [{**item("REQ-1"), "id": "approval:1", "link": "/", "action": "x", "since": None, "note": None, "escalates_at": None}], "handled": []})
        return MyWork(total=len(queues), queues=queues)
    monkeypatch.setattr(desk_summary.my_work_controller, "work_for", waiting)
    return SimpleNamespace(sent=sent, saved=saved)


def test_only_departments_with_work_and_people_with_an_address_get_one_and_admins_are_left_out(mail):
    assert desk_summary.send_due(NINE_IST) == 1
    assert [to for to, _, _ in mail.sent] == ["a@x.co"] and "Approvers" in mail.sent[0][1] and "REQ-1" in mail.sent[0][2]   # Accounts: nothing waiting; PO desk: no address
    assert mail.saved[desk_summary.LAST_SENT_KEY] == "2026-10-06"


def test_the_second_tick_the_same_morning_sends_nothing(mail):
    desk_summary.send_due(NINE_IST)
    assert desk_summary.send_due(NINE_IST.replace(minute=45)) == 0 and len(mail.sent) == 1


def test_switched_off_or_too_early_sends_nothing_and_does_not_use_up_the_day(mail, monkeypatch):
    monkeypatch.setattr(settings, "DESK_SUMMARY_ENABLED", False)
    assert desk_summary.send_due(NINE_IST) == 0 and desk_summary.LAST_SENT_KEY not in mail.saved
    monkeypatch.setattr(settings, "DESK_SUMMARY_ENABLED", True)
    assert desk_summary.send_due(datetime(2026, 10, 6, 1, 0)) == 0 and mail.sent == []


def test_a_failing_address_does_not_stop_the_others_or_cause_a_resend(mail, monkeypatch):
    def flaky(to, subject, body, html=None):
        if to == "a@x.co":
            raise OSError("smtp down")
    monkeypatch.setattr(desk_summary.email_client, "send_email", flaky)
    assert desk_summary.send_due(NINE_IST) == 0
    assert desk_summary.send_due(NINE_IST) == 0 and mail.saved[desk_summary.LAST_SENT_KEY] == "2026-10-06"       # the day is spent; no retry storm


def test_a_department_that_cannot_be_built_is_skipped_not_fatal(mail, monkeypatch):
    def broken(username, can):
        raise RuntimeError("db down")
    monkeypatch.setattr(desk_summary.my_work_controller, "work_for", broken)
    assert desk_summary.send_due(NINE_IST) == 0


# ---- the setting --------------------------------------------------------------------------------------------------------------------

def test_the_switch_and_the_hour_are_settings_with_sane_limits():
    keys = {t.key: t for t in tunables.CATALOG}
    assert keys["DESK_SUMMARY_ENABLED"].kind == "bool" and keys["DESK_SUMMARY_HOUR"].kind == "int"
    assert tunables.DEFAULTS["DESK_SUMMARY_ENABLED"] is True                             # opt in: nobody is e-mailed by surprise
    with pytest.raises(tunables.InvalidSetting):
        tunables.validate({"DESK_SUMMARY_HOUR": 24})
    assert tunables.validate({"DESK_SUMMARY_HOUR": 7, "DESK_SUMMARY_ENABLED": True}) == {"DESK_SUMMARY_HOUR": 7, "DESK_SUMMARY_ENABLED": True}
