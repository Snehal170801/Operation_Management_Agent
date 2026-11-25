"""The general "stuck too long" sweep: every open stage has a longest quiet time; the department is told once, the admin once later,
and moving the case on starts it afresh."""

from datetime import datetime, timedelta

import pytest

from app.core import stuck_policy as sp, tunables
from app.core.config import settings
from app.orchestrator import case_pipeline

from .fake_world import now, standard_world

HOURS = sp.limits(2, 48, 168)
NOW = datetime(2026, 10, 7, 12, 0)


def case(stage="awaiting_approval", quiet=60, status="open", cid="c1"):
    return {"case_id": cid, "case_number": "REQ-1", "items_summary": "cameras", "stage": stage, "status": status, "updated_at": NOW - timedelta(hours=quiet)}


# ---- the rule ---------------------------------------------------------------------------------------------------------------------------

def test_each_stage_uses_the_limit_for_its_kind():
    assert [c["case_id"] for c in sp.candidates(NOW, [case("created", 3, cid="a"), case("awaiting_approval", 3, cid="b"), case("po_issued", 3, cid="c")], HOURS)] == ["a"]
    assert {c["case_id"] for c in sp.candidates(NOW, [case("created", 3, cid="a"), case("awaiting_approval", 50, cid="b"), case("po_issued", 169, cid="c")], HOURS)} == {"a", "b", "c"}


def test_closed_cases_unknown_stages_and_zero_limits_are_never_stuck():
    assert sp.candidates(NOW, [case(status="closed"), case("completed"), case("somewhere_new")], HOURS) == []
    assert sp.candidates(NOW, [case("created", 99)], sp.limits(0, 48, 168)) == []                        # 0 switches that kind off
    assert sp.candidates(NOW, [case("awaiting_approval", 99)], sp.limits(2, 0, 168)) == []


def test_the_oldest_comes_first_and_the_department_is_the_stage_s():
    found = sp.candidates(NOW, [case("po_send_failed", 60, cid="a"), case("awaiting_approval", 90, cid="b")], HOURS)
    assert [f["case_id"] for f in found] == ["b", "a"] and [f["team"] for f in found] == ["approval", "po"]


def test_every_listed_stage_has_a_known_kind_and_department():
    from app.core.permissions import ALERT_PERMISSION
    for stage, (kind, team) in sp.STAGES.items():
        assert kind in HOURS and (team is None or team in ALERT_PERMISSION), stage


def test_only_events_since_the_last_move_count_and_the_next_step_is_never_repeated():
    since = NOW - timedelta(hours=60)
    ev = lambda t, ago: {"event_type": t, "created_at": NOW - timedelta(hours=ago)}      # noqa: E731
    assert sp.already_done([ev(sp.STUCK_EVENT, 100)], since) == set()                       # an earlier episode
    item = {"quiet_hours": 60, "limit_hours": 48}
    assert sp.next_step(item, set(), 24) == "notify"
    assert sp.next_step(item, {"notified"}, 24) is None                                      # not yet 24h after the limit
    assert sp.next_step({"quiet_hours": 80, "limit_hours": 48}, {"notified"}, 24) == "escalate"
    assert sp.next_step({"quiet_hours": 80, "limit_hours": 48}, {"notified", "escalated"}, 24) is None
    assert sp.next_step({"quiet_hours": 80, "limit_hours": 48}, {"notified", "admin_told"}, 24) is None     # the older rule already told the admin
    assert sp.next_step({"quiet_hours": 500, "limit_hours": 48}, {"notified"}, 0) is None                     # escalation switched off


# ---- the sweep ----------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    return standard_world(monkeypatch)


def stuck_case(w, stage="awaiting_approval", quiet=60):
    case_id = w.submit("50 cameras")
    w.cases[case_id].stage = stage
    w.cases[case_id].updated_at = now() - timedelta(hours=quiet)
    return case_id


def mails(w, text):
    return [m for m in w.emails_to("manager@x.co") if text in m[2]]


def test_a_stuck_case_is_noted_and_the_department_told_once_not_every_tick(w):
    case_id = stuck_case(w)
    assert case_pipeline.sweep_stuck_cases() == 1
    assert "case.stuck" in w.event_types(case_id) and mails(w, "has sat at 'awaiting approval'")
    assert case_pipeline.sweep_stuck_cases() == 0 and case_pipeline.sweep_stuck_cases() == 0
    assert w.event_types(case_id).count("case.stuck") == 1 and len(mails(w, "has sat at")) == 1


def test_still_stuck_a_day_later_the_admin_is_told_once_more_and_then_never_again(w):
    case_id = stuck_case(w, quiet=60)
    case_pipeline.sweep_stuck_cases()
    w.cases[case_id].updated_at = now() - timedelta(hours=48 + 25)
    assert case_pipeline.sweep_stuck_cases() == 1 and "case.stuck_escalated" in w.event_types(case_id)
    assert case_pipeline.sweep_stuck_cases() == 0
    assert w.event_types(case_id).count("case.stuck_escalated") == 1


def test_a_case_that_moves_and_sticks_again_is_told_about_again(w):
    case_id = stuck_case(w)
    case_pipeline.sweep_stuck_cases()
    w.cases[case_id].stage, w.cases[case_id].updated_at = "po_send_failed", now() - timedelta(hours=60)      # moved on, then quiet again
    w.events[case_id][-1].created_at = now() - timedelta(hours=100)                                           # (the earlier notice is from before)
    for e in w.events[case_id]:
        e.created_at = min(e.created_at, now() - timedelta(hours=100))
    assert case_pipeline.sweep_stuck_cases() == 1 and w.event_types(case_id).count("case.stuck") == 2


def test_a_healthy_case_a_closed_case_and_a_switched_off_sweep_send_nothing(w, monkeypatch):
    fresh = stuck_case(w, quiet=1)
    assert case_pipeline.sweep_stuck_cases() == 0 and "case.stuck" not in w.event_types(fresh)
    old = stuck_case(w, "completed", 999)
    w.cases[old].status = "closed"
    assert case_pipeline.sweep_stuck_cases() == 0
    stuck_case(w, quiet=99)
    for key in ("STUCK_AUTOMATIC_HOURS", "STUCK_PERSON_HOURS", "STUCK_WAITING_HOURS"):
        monkeypatch.setattr(settings, key, 0)
    assert case_pipeline.sweep_stuck_cases() == 0


def test_one_case_that_cannot_be_reported_does_not_stop_the_others(w, monkeypatch):
    first, second = stuck_case(w), stuck_case(w)
    real = case_pipeline.notification_agent.notify_case_stalled
    calls = []

    def flaky(case_id, reason, team=None):
        calls.append(case_id)
        if len(calls) == 1:
            raise RuntimeError("smtp down")
        return real(case_id, reason, team)
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled", flaky)
    assert case_pipeline.sweep_stuck_cases() == 1 and len(calls) == 2


def test_the_limits_are_settings_with_sane_ranges():
    keys = {t.key: t for t in tunables.CATALOG}
    for k in ("STUCK_AUTOMATIC_HOURS", "STUCK_PERSON_HOURS", "STUCK_WAITING_HOURS", "STUCK_ESCALATE_AFTER_HOURS"):
        assert keys[k].group == "stuck"
    assert tunables.validate({"STUCK_PERSON_HOURS": 12}) == {"STUCK_PERSON_HOURS": 12.0}
    with pytest.raises(tunables.InvalidSetting):
        tunables.validate({"STUCK_PERSON_HOURS": -1})


# ---- a first run over many old cases ------------------------------------------------------------------------------------------------------

def test_many_old_cases_are_reported_a_few_per_pass_oldest_first_and_every_one_in_the_end(w, monkeypatch):
    monkeypatch.setattr(settings, "STUCK_MAX_PER_TICK", 5)
    ids = [stuck_case(w, quiet=60 + n) for n in range(12)]                    # the last one is the oldest
    assert case_pipeline.sweep_stuck_cases() == 5
    told = [c for c in ids if "case.stuck" in w.event_types(c)]
    assert told == ids[-5:]                                                    # the oldest five first
    assert case_pipeline.sweep_stuck_cases() == 5 and case_pipeline.sweep_stuck_cases() == 2
    assert case_pipeline.sweep_stuck_cases() == 0 and all(w.event_types(c).count("case.stuck") == 1 for c in ids)


def test_a_failing_send_still_counts_toward_the_cap(w, monkeypatch):
    monkeypatch.setattr(settings, "STUCK_MAX_PER_TICK", 2)
    for n in range(4):
        stuck_case(w, quiet=60 + n)
    calls = []
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled", lambda *a, **k: (calls.append(1), (_ for _ in ()).throw(RuntimeError("down")))[1])
    assert case_pipeline.sweep_stuck_cases() == 0 and len(calls) == 2


def test_a_waiting_stage_uses_the_week_not_the_two_hours(w):
    quiet_waiting = [stuck_case(w, stage, 30) for stage in ("awaiting_quotes", "po_issued", "delivered")]          # 30h: far past 2h, well short of 168h
    assert case_pipeline.sweep_stuck_cases() == 0 and not any("case.stuck" in w.event_types(c) for c in quiet_waiting)
    old = stuck_case(w, "po_issued", 170)
    assert case_pipeline.sweep_stuck_cases() == 1 and "case.stuck" in w.event_types(old)
