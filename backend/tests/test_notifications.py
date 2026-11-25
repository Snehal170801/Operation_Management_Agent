from datetime import datetime
import os

for key, value in {
    "SQL_SERVER": "test",
    "SQL_DATABASE": "test",
    "SQL_DRIVER": "test",
    "SQL_TRUSTED_CONNECTION": "yes",
    "JWT_SECRET": "test-secret",
}.items():
    os.environ.setdefault(key, value)

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from app.agents import notification_agent  # noqa: E402
from app.orchestrator import case_pipeline  # noqa: E402

CASE = "3f2b8c1a-1111-4222-8333-444455556666"


def _stub_mail(monkeypatch, emails):
    sent, events = [], []
    monkeypatch.setattr(
        notification_agent.user_repository, "find_active_users_with_permission",
        lambda permission: [SimpleNamespace(email=e) for e in emails],
    )
    monkeypatch.setattr(notification_agent.email_client, "send_email",
                        lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(notification_agent.operations_agent, "publish_event",
                        lambda cid, t, **kw: events.append((t, kw.get("payload"))))
    return sent, events


def test_only_people_who_can_approve_are_notified(monkeypatch):
    asked = []
    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission",
                        lambda permission: asked.append(permission) or [SimpleNamespace(email="m@x.com")])
    monkeypatch.setattr(notification_agent.email_client, "send_email", lambda *a: None)
    monkeypatch.setattr(notification_agent.operations_agent, "publish_event", lambda *a, **k: None)
    notification_agent.notify_approval_needed(CASE, "Acme", None, ["x"])
    assert asked == ["approvals:write"]


@pytest.mark.parametrize("team, permission", [("vendor", "vendors:write"), ("po", "po:manage"),
                                                ("delivery", "delivery:confirm"), ("invoice", "invoices:decide")])
def test_each_kind_of_problem_goes_to_its_own_department(monkeypatch, team, permission):
    asked = []
    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission",
                        lambda p: asked.append(p) or [SimpleNamespace(email="d@x.com")])
    monkeypatch.setattr(notification_agent.email_client, "send_email", lambda *a: None)
    monkeypatch.setattr(notification_agent.operations_agent, "publish_event", lambda *a, **k: None)
    notification_agent.notify_case_stalled(CASE, "something", team=team)
    assert asked == [permission]


def test_a_department_with_nobody_in_it_falls_back_to_the_admins(monkeypatch):
    asked, sent = [], []
    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission",
                        lambda p: asked.append(p) or ([SimpleNamespace(email="admin@x.com")] if p == "system:write" else []))
    monkeypatch.setattr(notification_agent.email_client, "send_email", lambda to, s, b: sent.append(to))
    monkeypatch.setattr(notification_agent.operations_agent, "publish_event", lambda *a, **k: None)
    notification_agent.notify_case_stalled(CASE, "no supplier replied", team="vendor")
    assert asked == ["vendors:write", "system:write"] and sent == ["admin@x.com"]


def test_a_problem_with_no_department_goes_to_the_admins(monkeypatch):
    asked = []
    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission",
                        lambda p: asked.append(p) or [SimpleNamespace(email="admin@x.com")])
    monkeypatch.setattr(notification_agent.email_client, "send_email", lambda *a: None)
    monkeypatch.setattr(notification_agent.operations_agent, "publish_event", lambda *a, **k: None)
    notification_agent.notify_case_stalled(CASE, "an automatic step failed")
    assert asked == ["system:write"]


def test_approval_email_lists_reasons_and_goes_to_everyone(monkeypatch):
    sent, events = _stub_mail(monkeypatch, ["a@x.com", "b@x.com"])
    notification_agent.notify_approval_needed(CASE, "Acme", "Cheapest", ["Amount too high."])
    assert [s[0] for s in sent] == ["a@x.com", "b@x.com"]
    assert "Amount too high." in sent[0][2] and "Acme" in sent[0][2]
    assert events == [("notification.sent", {"kind": "approval_requested", "team": "approval", "sent": 2, "failed": 0})]


def test_reminder_is_labelled(monkeypatch):
    sent, events = _stub_mail(monkeypatch, ["a@x.com"])
    notification_agent.notify_approval_needed(CASE, "Acme", None, ["x"], reminder=True)
    assert sent[0][1].startswith("REMINDER")
    assert events[0][1]["kind"] == "approval_reminder"


def test_no_recipients_is_recorded_not_silent(monkeypatch):
    sent, events = _stub_mail(monkeypatch, [])
    notification_agent.notify_case_stalled(CASE, "no quotes")
    assert sent == [] and events[0][0] == "notification.no_recipients"


def test_one_bad_address_does_not_block_the_others(monkeypatch):
    sent, events = _stub_mail(monkeypatch, ["bad@x.com", "ok@x.com"])

    def flaky(to, subject, body):
        if to == "bad@x.com":
            raise OSError("smtp down")
        sent.append(to)

    monkeypatch.setattr(notification_agent.email_client, "send_email", flaky)
    notification_agent.notify_case_stalled(CASE, "no quotes")
    assert sent == ["ok@x.com"]
    assert events[0][1]["sent"] == 1 and events[0][1]["failed"] == 1


def _stub_ranking(monkeypatch, approval_status):
    alerts = []
    monkeypatch.setattr(case_pipeline.purchase_agent, "get_purchase_request", lambda cid: {"items": [], "needed_by": None, "urgent": False})
    monkeypatch.setattr(case_pipeline.vendor_agent, "rank_vendors", lambda cid, needed_by=None: None)
    monkeypatch.setattr(case_pipeline.approval_agent, "review_vendor_selection",
                        lambda cid, needed_by=None: {"status": approval_status, "reasons": ["Too big"]})
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_vendor_selection",
                        lambda cid: {"vendor_name": "Acme", "rationale": "Cheapest"})
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_approval_needed",
                        lambda *a, **k: alerts.append(a))
    return alerts


def test_human_needed_triggers_notification(monkeypatch):
    alerts = _stub_ranking(monkeypatch, "pending")
    case_pipeline.rank_and_review(CASE)
    assert alerts == [(CASE, "Acme", "Cheapest", ["Too big"])]


def test_auto_approved_notifies_nobody(monkeypatch):
    alerts = _stub_ranking(monkeypatch, "auto_approved")
    monkeypatch.setattr(case_pipeline, "_issue_purchase_order_safely", lambda cid: None)
    case_pipeline.rank_and_review(CASE)
    assert alerts == []


def test_stale_approvals_are_reminded_and_counted(monkeypatch):
    reminded, notified = [], []
    monkeypatch.setattr(case_pipeline.operations_agent, "get_all_cases", lambda r=None: [])
    monkeypatch.setattr(case_pipeline.approval_agent, "get_approvals_needing_reminder",
                        lambda cutoff, cap: [{"approval_id": "ap1", "case_id": CASE, "reasons": ["x"], "created_at": datetime(2020, 1, 1), "last_reminded_at": None}])
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_vendor_selection",
                        lambda cid: {"vendor_name": "Acme", "rationale": None})
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_approval_needed",
                        lambda *a, **k: notified.append(k.get("reminder")))
    monkeypatch.setattr(case_pipeline.approval_agent, "mark_reminded", lambda aid: reminded.append(aid))
    assert case_pipeline.remind_pending_approvals() == 1
    assert reminded == ["ap1"] and notified == [True]
