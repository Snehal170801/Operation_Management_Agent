"""A problem that sits too long is passed to the admin once, and the person's queue shows it as late."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.agents import notification_agent
from app.core.escalation import due_escalations
from app.core.my_work import build_my_work
from app.orchestrator import case_pipeline

NOW = datetime(2026, 10, 2, 12, 0)
H = 24


def ago(hours):
    return NOW - timedelta(hours=hours)


def case(n, stage, hours_ago, status="open"):
    return {"case_id": f"C{n}", "case_number": f"REQ-2026-000{n}", "items_summary": f"Item {n}", "stage": stage, "status": status, "updated_at": ago(hours_ago),
            "requester_id": "alice@x.co"}


def approval(n, hours_ago, status="pending"):
    return {"approval_id": f"AP{n}", "case_id": f"C{n}", "status": status, "created_at": ago(hours_ago), "reasons": ["x"]}


def invoice(n, hours_ago, status="mismatch"):
    return {"invoice_id": f"IN{n}", "case_id": f"C{n}", "status": status, "created_at": ago(hours_ago), "invoice_number": "INV", "vendor_name": "A", "po_number": "PO-1"}


# ------------------------------------------------------------------------------------------- what is overdue

def test_only_things_that_waited_longer_than_the_limit_are_escalated():
    cases = [case(1, "sourcing_stalled", 30), case(2, "sourcing_stalled", 5), case(3, "po_send_failed", 25), case(4, "delivery_late", 49)]
    found = due_escalations(NOW, H, [], cases, [], set())
    assert [f["case_number"] for f in found] == ["REQ-2026-0004", "REQ-2026-0001", "REQ-2026-0003"]      # longest waiting first
    assert found[0]["hours_waiting"] == 49.0 and found[0]["kind"] == "delivery_late"


def test_old_pending_approvals_and_mismatching_invoices_are_escalated_too():
    cases = [case(1, "awaiting_approval", 2), case(2, "po_issued", 2)]
    found = due_escalations(NOW, H, [approval(1, 30)], cases, [invoice(2, 40)], set())
    assert {(f["kind"], f["ref"]) for f in found} == {("approval", "ap1"), ("invoice", "in2")}
    assert all("waiting" in f["what"] or "does not match" in f["what"] for f in found)


def test_things_already_escalated_are_not_escalated_again():
    cases = [case(1, "sourcing_stalled", 30)]
    assert due_escalations(NOW, H, [approval(1, 30)], cases, [], {("approval", "ap1"), ("sourcing_stalled", "c1")}) == []


def test_decided_approvals_closed_cases_fine_invoices_and_ordinary_stages_are_left_alone():
    cases = [case(1, "sourcing_stalled", 99, status="closed"), case(2, "po_issued", 99), case(3, "awaiting_quotes", 99)]
    assert due_escalations(NOW, H, [approval(1, 99, status="approved")], cases, [invoice(2, 99, status="matched")], set()) == []


def test_a_limit_of_zero_switches_escalation_off():
    assert due_escalations(NOW, 0, [approval(1, 999)], [case(1, "sourcing_stalled", 999)], [invoice(1, 999)], set()) == []


# ------------------------------------------------------------------------------------------- telling the admin

def test_an_escalation_goes_to_the_admins_and_says_how_long_it_has_waited(monkeypatch):
    asked, sent = [], []
    monkeypatch.setattr(notification_agent.user_repository, "find_active_users_with_permission",
                        lambda p: asked.append(p) or [SimpleNamespace(email="boss@x.co")])
    monkeypatch.setattr(notification_agent.email_client, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(notification_agent.operations_agent, "publish_event", lambda *a, **k: None)
    notification_agent.notify_escalation("C1", "A delivery is overdue", 49.0, "REQ-2026-0004 · Item 4")
    assert asked == ["system:write"] and sent[0][0] == "boss@x.co"
    assert sent[0][1] == "ESCALATED after 49h - A delivery is overdue" and "REQ-2026-0004 · Item 4" in sent[0][2] and "49 hours" in sent[0][2]


# ------------------------------------------------------------------------------------------- the pipeline

def stub_world(monkeypatch, events):
    told, recorded = [], []
    monkeypatch.setattr(case_pipeline.settings, "ESCALATE_AFTER_HOURS", 24.0)
    monkeypatch.setattr(case_pipeline.approval_agent, "get_approvals", lambda status=None, case_id=None: [approval(1, 30)])
    monkeypatch.setattr(case_pipeline.operations_agent, "get_all_cases", lambda r=None: [case(1, "awaiting_approval", 30), case(2, "sourcing_stalled", 50)])
    monkeypatch.setattr(case_pipeline.invoice_agent, "list_invoices", lambda status=None: [])
    monkeypatch.setattr(case_pipeline.operations_agent, "get_case_events", lambda cid: events.get(cid, []))
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_escalation", lambda cid, what, hours, label=None: told.append((cid, what, hours, label)))
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", lambda cid, t, **kw: recorded.append((cid, t, kw["payload"])))
    return told, recorded


def test_overdue_problems_are_escalated_once_and_remembered_on_the_case(monkeypatch):
    told, recorded = stub_world(monkeypatch, {})
    assert case_pipeline.escalate_overdue() == 2
    assert {t[0] for t in told} == {"C1", "C2"} and told[0][3] == "REQ-2026-0002 · Item 2"      # the oldest (50h) first
    assert {(r[1], r[2]["kind"], r[2]["ref"]) for r in recorded} == {("escalation.sent", "approval", "ap1"), ("escalation.sent", "sourcing_stalled", "c2")}


def test_the_same_problem_is_not_escalated_on_every_tick(monkeypatch):
    done = {"C1": [{"event_type": "escalation.sent", "payload": {"kind": "approval", "ref": "ap1"}}],
            "C2": [{"event_type": "escalation.sent", "payload": {"kind": "sourcing_stalled", "ref": "c2"}}]}
    told, recorded = stub_world(monkeypatch, done)
    assert case_pipeline.escalate_overdue() == 0 and told == [] and recorded == []


def test_escalation_does_nothing_when_switched_off(monkeypatch):
    told, _ = stub_world(monkeypatch, {})
    monkeypatch.setattr(case_pipeline.settings, "ESCALATE_AFTER_HOURS", 0.0)
    assert case_pipeline.escalate_overdue() == 0 and told == []


# ------------------------------------------------------------------------------------------- the person's queue

def test_late_items_show_as_urgent_with_a_note_that_the_admin_was_told():
    cases = [case(1, "awaiting_approval", 30), case(2, "awaiting_approval", 2)]
    approvals = [approval(1, 30), approval(2, 2)]
    result = build_my_work("apr", lambda p: p == "approvals:write", approvals, cases, [], [], [], NOW, escalate_after_hours=24)
    items = result["queues"][0]["items"]
    assert items[0]["id"] == "approval:AP1" and items[0]["urgent"] and "admin has been told" in items[0]["note"]
    assert not items[1]["urgent"] and items[1]["note"] is None


def test_without_a_limit_nothing_is_marked_late():
    result = build_my_work("apr", lambda p: p == "approvals:write", [approval(1, 300)], [case(1, "awaiting_approval", 300)], [], [], [], NOW)
    assert not result["queues"][0]["items"][0]["urgent"]
