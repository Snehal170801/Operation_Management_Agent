"""Approver leave and the backup approver: who is asked while someone is away, and that nothing ever goes unanswered."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.agents import notification_agent
from app.controllers import user_controller
from app.core import agent_cases as ac, approver_leave as al
from app.core.exceptions import InvalidInput
from app.models.auth_schemas import CurrentUser, UpdateUserRequest
from app.orchestrator import case_pipeline

from .fake_world import standard_world

TODAY = date(2026, 10, 8)


def p(uid, name=None, email="auto", role="manager", active=True, can=True, start=None, end=None, delegate=None):
    name = name or uid
    return {"user_id": uid, "username": name, "email": name + "@x.co" if email == "auto" else email, "role": role, "active": active, "can_approve": can,
            "on_leave_from": start, "on_leave_until": end, "delegate_user_id": delegate}


def directory(*people):
    return {x["user_id"].lower(): x for x in people}


# ---- the rule -------------------------------------------------------------------------------------------------------------------------

def test_leave_dates_include_both_ends_and_a_single_date_is_open_ended():
    away = p("a", start=date(2026, 10, 5), end=date(2026, 10, 8))
    assert al.on_leave(away, TODAY) and al.on_leave(away, date(2026, 10, 5)) and not al.on_leave(away, date(2026, 10, 9)) and not al.on_leave(away, date(2026, 10, 4))
    assert al.on_leave(p("a", start=date(2026, 10, 1)), TODAY) and not al.on_leave(p("a", start=date(2026, 10, 9)), TODAY)       # from a date, no end
    assert al.on_leave(p("a", end=date(2026, 10, 20)), TODAY) and not al.on_leave(p("a", end=date(2026, 10, 7)), TODAY)          # until a date
    assert not al.on_leave(p("a"), TODAY)


def test_leave_cannot_end_before_it_starts():
    al.check_leave(date(2026, 10, 1), date(2026, 10, 1))
    al.check_leave(None, date(2026, 10, 1))
    with pytest.raises(InvalidInput):
        al.check_leave(date(2026, 10, 2), date(2026, 10, 1))


def test_an_approver_on_leave_is_replaced_by_the_delegate_and_one_who_is_not_stays():
    away, backup, here = p("a", start=TODAY, end=TODAY, delegate="b"), p("b"), p("c")
    result = al.effective_approvers([away, here], directory(away, backup, here), TODAY)
    assert [x["username"] for x in result["askable"]] == ["b", "c"] and result["delegations"] == [{"from": "a", "to": "b"}] and result["unreachable"] == []


def test_two_people_naming_the_same_delegate_ask_them_once():
    a, b, d = p("a", start=TODAY, delegate="d"), p("b", start=TODAY, delegate="d"), p("d")
    result = al.effective_approvers([a, b], directory(a, b, d), TODAY)
    assert [x["username"] for x in result["askable"]] == ["d"] and len(result["delegations"]) == 2


def test_an_unusable_delegate_is_skipped_for_the_next_one_but_never_more_than_two_hops():
    away = p("a", start=TODAY, delegate="b")
    also_away = p("b", start=TODAY, delegate="c")
    third = p("c")
    assert al.delegate_for(away, directory(away, also_away, third), TODAY)["username"] == "c"            # b is away too: c covers
    far = p("c", start=TODAY, delegate="d")
    assert al.delegate_for(away, directory(away, also_away, far, p("d")), TODAY) is None                  # a -> b -> c -> d is too far
    for bad in (p("b", active=False), p("b", email=None), p("b", can=False)):
        assert al.delegate_for(away, directory(away, bad), TODAY) is None, bad


def test_a_missing_delegate_a_loop_or_no_delegate_at_all_means_nobody_covers():
    assert al.delegate_for(p("a", start=TODAY), {}, TODAY) is None
    assert al.delegate_for(p("a", start=TODAY, delegate="zzz"), {}, TODAY) is None
    a, b = p("a", start=TODAY, delegate="b"), p("b", start=TODAY, delegate="a")
    assert al.delegate_for(a, directory(a, b), TODAY) is None
    assert al.effective_approvers([a], directory(a, b), TODAY)["unreachable"] == ["a"]


# ---- the cover check ------------------------------------------------------------------------------------------------------------------

def test_with_a_delegate_the_request_is_covered_and_the_delegation_is_reported():
    away, backup = p("a", start=TODAY, delegate="b"), p("b")
    cover = ac.approver_cover([away, p("admin", role="admin")], "ravi", directory(away, backup, p("admin", role="admin")), TODAY)
    assert cover["delegations"] == [{"from": "a", "to": "b"}] and cover["reason"] is None


def test_everyone_on_leave_with_nobody_to_cover_goes_to_the_admins_with_that_reason():
    away = p("a", start=TODAY)
    cover = ac.approver_cover([away], "ravi", directory(away), TODAY)
    assert cover["eligible"] == [] and "on leave" in cover["reason"] and "a" in cover["reason"]


def test_leave_changes_nothing_when_nobody_is_away():
    assert ac.approver_cover([p("a")], "ravi", {}, TODAY)["reason"] is None


# ---- through the pipeline -----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    monkeypatch.setattr(notification_agent.access, "has_permission", lambda role, permission: True)
    return standard_world(monkeypatch)


def row(uid, name, **kw):
    return SimpleNamespace(user_id=uid, username=name, email=name + "@x.co", role="manager", is_active=True, on_leave_from=None, on_leave_until=None, delegate_user_id=None, **kw)


def staff(monkeypatch, *rows, everyone=()):
    """`rows` are the approvers; `everyone` also holds people who are not approvers but may be named as a backup."""
    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission", lambda permission: list(rows))
    monkeypatch.setattr(notification_agent.user_repository, "find_all_users", lambda: [*rows, *everyone])
    monkeypatch.setattr(notification_agent, "today_india", lambda: TODAY)


def pending(w):
    from .test_end_to_end import QUOTE_42K
    case_id = w.submit("50 cameras", requester="ravi@x.co")
    for name, price in (("Acme", "900,000"), ("Globex", "950,000")):
        w.reply(case_id, name, f"Total Rs {price}. Delivery 7 days. Terms: net 30")
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval"
    return case_id


def test_an_approver_on_leave_is_not_emailed_their_delegate_is_and_the_case_says_so(w, monkeypatch):
    away = row("a", "anna")
    away.on_leave_from, away.on_leave_until, away.delegate_user_id = TODAY, TODAY, "b"
    staff(monkeypatch, away, everyone=[row("b", "bob")])
    case_id = pending(w)
    assert not w.emails_to("anna@x.co") and any("Approval needed" in m[1] for m in w.emails_to("bob@x.co"))
    delegated = [e for e in w.events[case_id] if e.event_type == "approval.delegated"]
    assert len(delegated) == 1 and delegated[0].payload["from"] == "anna" and delegated[0].payload["to"] == "bob"
    assert "approval.routed_to_admin" not in w.event_types(case_id)


def test_the_delegation_is_recorded_once_even_if_checked_again(w, monkeypatch):
    away = row("a", "anna")
    away.on_leave_from, away.delegate_user_id = TODAY, "b"
    staff(monkeypatch, away, everyone=[row("b", "bob")])
    case_id = pending(w)
    approval_id = next(e.payload["approval_id"] for e in w.events[case_id] if e.event_type == "approval.delegated")
    case_pipeline.check_approver_cover(case_id, approval_id)
    assert w.event_types(case_id).count("approval.delegated") == 1


def test_no_delegate_means_the_admins_are_told_why_and_nothing_is_silent(w, monkeypatch):
    away = row("a", "anna")
    away.on_leave_from = TODAY
    staff(monkeypatch, away)
    case_id = pending(w)
    routed = [e for e in w.events[case_id] if e.event_type == "approval.routed_to_admin"]
    assert len(routed) == 1 and "on leave" in routed[0].payload["reason"]


def test_when_the_leave_is_over_the_approver_is_asked_again(w, monkeypatch):
    back = row("a", "anna")
    back.on_leave_from, back.on_leave_until, back.delegate_user_id = date(2026, 10, 1), date(2026, 10, 7), "b"          # ended yesterday
    staff(monkeypatch, back, everyone=[row("b", "bob")])
    pending(w)
    assert any("Approval needed" in m[1] for m in w.emails_to("anna@x.co")) and not w.emails_to("bob@x.co")


def test_a_failure_reading_the_users_never_stops_the_approval_email(w, monkeypatch):
    away = row("a", "anna")
    away.on_leave_from = TODAY
    staff(monkeypatch, away, row("c", "cara"))
    monkeypatch.setattr(notification_agent.user_repository, "find_all_users", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    pending(w)
    assert w.emails_to("cara@x.co")                                                       # cara was still asked


def test_changing_someones_leave_sends_the_waiting_approval_to_whoever_is_asked_now(w, monkeypatch):
    anna, bob = row("a", "anna"), row("b", "bob")
    staff(monkeypatch, anna, everyone=[bob])
    case_id = pending(w)
    assert w.emails_to("anna@x.co") and not w.emails_to("bob@x.co")
    mark = len(w.sent)
    anna.on_leave_from, anna.delegate_user_id = TODAY, "b"
    out = case_pipeline.reroute_pending_approvals()
    assert out["renotified"] == 1
    assert [m for m in w.sent[mark:] if m[0] == "bob@x.co" and "REMINDER" in m[1]] and not [m for m in w.sent[mark:] if m[0] == "anna@x.co"]
    assert case_id


# ---- editing leave (controller) ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def users(monkeypatch):
    rows = {"t": SimpleNamespace(user_id="t", username="tara", display_name="Tara", email="tara@x.co", role="manager", is_active=True, locked_until=None, last_login_at=None,
                                 created_at=TODAY, on_leave_from=None, on_leave_until=None, delegate_user_id=None, failed_attempts=0),
            "b": SimpleNamespace(user_id="b", username="bob", display_name="Bob", email="bob@x.co", role="manager", is_active=True, locked_until=None, last_login_at=None,
                                 created_at=TODAY, on_leave_from=None, on_leave_until=None, delegate_user_id=None, failed_attempts=0),
            "x": SimpleNamespace(user_id="x", username="xena", display_name="Xena", email="xena@x.co", role="viewer", is_active=True, locked_until=None, last_login_at=None,
                                 created_at=TODAY, on_leave_from=None, on_leave_until=None, delegate_user_id=None, failed_attempts=0)}
    saved, rerouted = [], []
    repo = user_controller.user_repository
    monkeypatch.setattr(repo, "find_user_by_id", lambda uid: rows.get(str(uid)))
    monkeypatch.setattr(repo, "find_all_users", lambda: list(rows.values()))
    monkeypatch.setattr(repo, "update_user", lambda *a, **k: None)
    monkeypatch.setattr(repo, "set_leave", lambda uid, f, u, d: saved.append((uid, f, u, d)) or setattr(rows[uid], "on_leave_from", f) or setattr(rows[uid], "on_leave_until", u) or setattr(rows[uid], "delegate_user_id", d))
    monkeypatch.setattr(user_controller.role_repository, "find_permissions_by_role", lambda: {"manager": {"approvals:write"}, "viewer": {"cases:read"}})
    monkeypatch.setattr(user_controller.access, "has_permission", lambda role, permission: role == "manager" and permission == "approvals:write" or role == "admin")
    monkeypatch.setattr(user_controller.access, "invalidate", lambda: None)
    monkeypatch.setattr(user_controller, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(user_controller.case_pipeline, "reroute_pending_approvals", lambda: rerouted.append(1) or {})
    return SimpleNamespace(rows=rows, saved=saved, rerouted=rerouted, admin=CurrentUser(user_id="adm", username="admin", role="admin"))


def update(users, **fields):
    return user_controller.update_user("t", UpdateUserRequest(**fields), users.admin)


def test_an_admin_can_set_leave_and_a_backup_and_waiting_approvals_are_re_routed(users):
    out = update(users, on_leave_from=date(2026, 10, 10), on_leave_until=date(2026, 10, 20), delegate_user_id="b")
    assert users.saved == [("t", date(2026, 10, 10), date(2026, 10, 20), "b")] and users.rerouted == [1]
    assert out.delegate_user_id == "b" and out.delegate_name == "Bob" and out.on_leave_from == date(2026, 10, 10)


def test_only_the_fields_that_are_sent_change_and_null_clears(users):
    update(users, on_leave_from=date(2026, 10, 10), on_leave_until=date(2026, 10, 20), delegate_user_id="b")
    update(users, on_leave_until=date(2026, 10, 25))
    assert users.saved[-1] == ("t", date(2026, 10, 10), date(2026, 10, 25), "b")
    update(users, on_leave_from=None, on_leave_until=None, delegate_user_id=None)
    assert users.saved[-1] == ("t", None, None, None)
    count = len(users.saved)
    update(users, display_name="Tara T")                                                   # unrelated edit: leave untouched, nothing re-routed
    assert len(users.saved) == count


def test_bad_leave_edits_are_refused_and_nothing_is_saved(users):
    for fields in ({"on_leave_from": date(2026, 10, 20), "on_leave_until": date(2026, 10, 10)},
                   {"delegate_user_id": "t"},                      # themselves
                   {"delegate_user_id": "nobody"},                 # unknown
                   {"delegate_user_id": "x"}):                      # cannot approve
        with pytest.raises(InvalidInput):
            update(users, **fields)
    users.rows["b"].is_active = False
    with pytest.raises(InvalidInput):
        update(users, delegate_user_id="b")                         # deactivated
    assert users.saved == [] and users.rerouted == []
