"""The weekly admin summary and the daily department summary: on by default, once per period, never again after a restart or from a second copy."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core import tunables, weekly_summary as rules
from app.core.config import settings
from app.orchestrator import desk_summary, weekly_summary

# Monday 2026-10-05, 09:00 India time = 03:30 UTC
MON_9 = datetime(2026, 10, 5, 3, 30)


# ---- when ---------------------------------------------------------------------------------------------------------------------------------

def test_the_week_is_identified_by_its_monday_in_india_time():
    assert rules.week_key(MON_9) == "2026-10-05"
    assert rules.week_key(datetime(2026, 10, 11, 20, 0)) == "2026-10-12"          # Sunday 20:00 UTC is already Monday in India
    assert rules.week_key(datetime(2026, 10, 11, 17, 0)) == "2026-10-05"          # Sunday 22:30 India time is still that week


def test_it_is_due_from_the_set_day_and_hour_for_a_day_and_once_a_week():
    assert rules.is_due(MON_9, True, 0, 9, None)
    assert not rules.is_due(datetime(2026, 10, 5, 3, 0), True, 0, 9, None)                      # 08:30: too early
    assert rules.is_due(datetime(2026, 10, 5, 12, 0), True, 0, 9, None)                         # 17:30: a server that was down still sends
    assert not rules.is_due(datetime(2026, 10, 6, 5, 0), True, 0, 9, None)                      # Tuesday: the window has passed
    assert not rules.is_due(MON_9, True, 0, 9, "2026-10-05")                                    # already sent for this week
    assert rules.is_due(MON_9, True, 0, 9, "2026-09-28")                                        # last week's does not count
    assert not rules.is_due(MON_9, False, 0, 9, None)
    assert rules.is_due(datetime(2026, 10, 9, 3, 30), True, 4, 9, None)                         # Friday, if that is the day set


def test_a_nonsense_day_or_hour_never_sends():
    for day, hour in ((7, 9), (-1, 9), (0, 24), (0, -1)):
        assert not rules.is_due(MON_9, True, day, hour, None)


def report(**over):
    base = {"totals": {"requests": 12, "completed": 7, "from_stock": 2, "rejected": 1, "cancelled": 1, "in_progress": 3, "spend": 1234567.0, "orders": 8, "avg_cycle_hours": 72.0},
            "automation": {"touchless": 6, "needed_a_person": 4, "touchless_pct": 60}, "spend": {"by_vendor": [{"vendor": "Acme", "total": 900000.0, "orders": 5}]},
            "stuck": [{"label": "Waiting for an approval", "count": 2, "oldest_hours": 50.0}]}
    return {**base, **over}


def test_the_text_says_what_happened_and_what_is_waiting():
    waiting = {"total": 5, "urgent": 1, "by_department": [("Approvers", 3), ("Accounts", 2), ("PO desk", 0)]}
    text = rules.body(report(), waiting, "http://app")
    assert "12 started, 7 completed, 2 filled from stock, 1 not approved, 1 cancelled, 3 still open" in text
    assert "worth Rs 1,234,567" in text and "3.0 days" in text and "60%" in text and "Acme" in text and "Waiting for an approval: 2" in text
    assert "Waiting for people right now: 5 (1 urgent)" in text and "Approvers: 3" in text and "PO desk" not in text and "http://app/reports" in text
    assert rules.subject(report()) == "Weekly summary: 12 request(s), 7 completed, Rs 1,234,567 ordered"


def test_a_quiet_week_still_reads_well():
    empty = report(totals={**report()["totals"], "avg_cycle_hours": None}, automation={"touchless": 0, "needed_a_person": 0, "touchless_pct": None}, spend={"by_vendor": []}, stuck=[])
    text = rules.body(empty, {"total": 0, "urgent": 0, "by_department": []}, "http://app")
    assert "Nothing is waiting for a person right now" in text and "Average time" not in text and "Most ordered from" not in text and "Handled with no person" not in text


# ---- sending ------------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def mail(monkeypatch):
    sent, saved, built = [], {}, []
    admins = [SimpleNamespace(email="boss@x.co", role="admin"), SimpleNamespace(email="cfo@x.co", role="admin"), SimpleNamespace(email=None, role="admin")]
    monkeypatch.setattr(weekly_summary.user_repository, "find_active_users_with_permission", lambda p: admins if p == "system:write" else [])
    monkeypatch.setattr(weekly_summary.automation_repository, "get_setting", lambda k: SimpleNamespace(setting_value=saved[k]) if k in saved else None)

    def claim(k, v, by):
        if saved.get(k) == v:
            return False
        saved[k] = v
        return True
    monkeypatch.setattr(weekly_summary.automation_repository, "claim_setting", claim)
    monkeypatch.setattr(weekly_summary.email_client, "send_email", lambda to, subject, body, html=None: sent.append((to, subject, body)))
    monkeypatch.setattr(weekly_summary.report_controller, "get_report", lambda days: built.append(days) or SimpleNamespace(model_dump=lambda: report()))
    monkeypatch.setattr(weekly_summary, "_waiting", lambda: {"total": 0, "urgent": 0, "by_department": []})
    monkeypatch.setattr(settings, "WEEKLY_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "WEEKLY_SUMMARY_DAY", 0)
    monkeypatch.setattr(settings, "WEEKLY_SUMMARY_HOUR", 9)
    return SimpleNamespace(sent=sent, saved=saved, built=built)


def test_the_admins_with_an_address_get_one_each_and_the_report_covers_seven_days(mail):
    assert weekly_summary.send_due(MON_9) == 2
    assert [to for to, _, _ in mail.sent] == ["boss@x.co", "cfo@x.co"] and mail.built == [7] and "Weekly summary" in mail.sent[0][1]
    assert mail.saved[weekly_summary.LAST_SENT_KEY] == "2026-10-05"


def test_a_restart_or_a_second_tick_the_same_week_sends_nothing(mail):
    weekly_summary.send_due(MON_9)
    assert weekly_summary.send_due(MON_9.replace(minute=45)) == 0 and len(mail.sent) == 2           # the marker is in the database: a restart reads it


def test_a_second_copy_of_the_app_that_loses_the_claim_sends_nothing(mail, monkeypatch):
    real_get = weekly_summary.automation_repository.get_setting
    monkeypatch.setattr(weekly_summary.automation_repository, "get_setting", lambda k: None)         # (it has not yet seen the other copy's marker)
    weekly_summary.send_due(MON_9)
    assert weekly_summary.send_due(MON_9) == 0 and len(mail.sent) == 2                               # the atomic claim says someone already took this week
    assert real_get(weekly_summary.LAST_SENT_KEY) is not None


def test_next_week_is_sent_again(mail):
    weekly_summary.send_due(MON_9)
    assert weekly_summary.send_due(datetime(2026, 10, 12, 3, 30)) == 2 and len(mail.sent) == 4


def test_switched_off_not_due_or_no_admin_address_sends_nothing_and_does_not_use_up_the_week(mail, monkeypatch):
    monkeypatch.setattr(settings, "WEEKLY_SUMMARY_ENABLED", False)
    assert weekly_summary.send_due(MON_9) == 0 and weekly_summary.LAST_SENT_KEY not in mail.saved
    monkeypatch.setattr(settings, "WEEKLY_SUMMARY_ENABLED", True)
    assert weekly_summary.send_due(datetime(2026, 10, 6, 5, 0)) == 0
    monkeypatch.setattr(weekly_summary.user_repository, "find_active_users_with_permission", lambda p: [SimpleNamespace(email=None, role="admin")])
    assert weekly_summary.send_due(MON_9) == 0 and weekly_summary.LAST_SENT_KEY not in mail.saved   # nobody to tell: the week stays open for when someone has an address


def test_a_failing_address_does_not_stop_the_others_and_a_failing_report_sends_nothing(mail, monkeypatch):
    def flaky(to, subject, body, html=None):
        if to == "boss@x.co":
            raise OSError("smtp down")
        mail.sent.append((to, subject, body))
    monkeypatch.setattr(weekly_summary.email_client, "send_email", flaky)
    assert weekly_summary.send_due(MON_9) == 1 and [to for to, _, _ in mail.sent] == ["cfo@x.co"]
    monkeypatch.setattr(weekly_summary.report_controller, "get_report", lambda days: (_ for _ in ()).throw(RuntimeError("db down")))
    assert weekly_summary.send_due(datetime(2026, 10, 12, 3, 30)) == 0


def test_the_worker_runs_both_summaries_every_pass_and_a_failure_does_not_stop_the_pass(monkeypatch):
    from app.orchestrator import worker
    from .fake_world import standard_world
    standard_world(monkeypatch)
    calls = []
    monkeypatch.setattr(worker.weekly_summary, "send_due", lambda: calls.append("weekly") or (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(worker.desk_summary, "send_due", lambda: calls.append("daily"))
    worker.run_once()
    assert set(calls) == {"weekly", "daily"}


# ---- the settings: on by default ----------------------------------------------------------------------------------------------------------

def test_both_summaries_are_on_by_default_and_configurable():
    keys = {t.key: t for t in tunables.CATALOG}
    assert tunables.DEFAULTS["WEEKLY_SUMMARY_ENABLED"] is True and tunables.DEFAULTS["DESK_SUMMARY_ENABLED"] is True
    assert keys["WEEKLY_SUMMARY_DAY"].group == "summary" and keys["WEEKLY_SUMMARY_ENABLED"].kind == "bool"
    assert tunables.validate({"WEEKLY_SUMMARY_DAY": 4, "WEEKLY_SUMMARY_HOUR": 17}) == {"WEEKLY_SUMMARY_DAY": 4, "WEEKLY_SUMMARY_HOUR": 17}
    for bad in ({"WEEKLY_SUMMARY_DAY": 7}, {"WEEKLY_SUMMARY_HOUR": 24}, {"WEEKLY_SUMMARY_DAY": -1}):
        with pytest.raises(tunables.InvalidSetting):
            tunables.validate(bad)


def test_the_daily_one_also_loses_to_an_earlier_claim(monkeypatch):
    saved, sent = {desk_summary.LAST_SENT_KEY: "2026-10-05"}, []
    monkeypatch.setattr(desk_summary.automation_repository, "get_setting", lambda k: None)          # (a stale read)
    monkeypatch.setattr(desk_summary.automation_repository, "claim_setting", lambda k, v, by: False if saved.get(k) == v else True)
    monkeypatch.setattr(desk_summary.email_client, "send_email", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(settings, "DESK_SUMMARY_ENABLED", True)
    monkeypatch.setattr(settings, "DESK_SUMMARY_HOUR", 9)
    assert desk_summary.send_due(MON_9) == 0 and sent == []
