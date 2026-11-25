"""A rejected invoice the supplier never corrects: remind them on schedule, then tell Accounts, then the admin."""

from datetime import datetime, timedelta

from app.agents import invoice_agent
from app.core.invoice_chase_policy import correction_overdue, next_invoice_chase_action
from app.core.my_work import build_my_work
from app.orchestrator import case_pipeline

NOW = datetime(2026, 10, 10, 12, 0)
H = 24  # hours between reminders
MAX = 2
ESC = 24


def ago(hours):
    return NOW - timedelta(hours=hours)


def act(rejected_hours_ago, chases_hours_ago=(), alerted_hours_ago=None, escalated=False, can_email=True):
    return next_invoice_chase_action(ago(rejected_hours_ago), [ago(h) for h in chases_hours_ago],
                                     None if alerted_hours_ago is None else ago(alerted_hours_ago), escalated, NOW, H, MAX, ESC, can_email)


# ------------------------------------------------------------------------------------------- the schedule

def test_nothing_happens_until_a_day_has_passed_since_the_rejection():
    assert act(2) == "wait" and act(23) == "wait"


def test_the_supplier_is_reminded_a_day_after_the_rejection_and_again_a_day_later():
    assert act(25) == "remind"                                  # first reminder
    assert act(49, chases_hours_ago=[24]) == "remind"           # second, a day after the first
    assert act(30, chases_hours_ago=[5]) == "wait"              # but not before a day has passed since the last one


def test_after_the_last_reminder_and_another_day_accounts_is_told():
    assert act(80, chases_hours_ago=[50, 26]) == "alert"
    assert act(60, chases_hours_ago=[40, 10]) == "wait"          # that day has not passed yet


def test_if_accounts_does_nothing_the_admin_is_told_after_the_escalation_time():
    assert act(120, chases_hours_ago=[90, 66], alerted_hours_ago=30) == "escalate"
    assert act(120, chases_hours_ago=[90, 66], alerted_hours_ago=5) == "wait"


def test_it_is_all_one_time_each_the_admin_already_knowing_ends_it():
    assert act(500, chases_hours_ago=[90, 66], alerted_hours_ago=300, escalated=True) == "wait"
    assert act(120, chases_hours_ago=[90, 66], alerted_hours_ago=30, escalated=False) == "escalate"


def test_a_supplier_with_no_email_cannot_be_reminded_so_accounts_is_told_straight_away():
    assert act(25, can_email=False) == "alert" and act(10, can_email=False) == "wait"


def test_it_counts_as_overdue_once_every_reminder_and_a_final_day_have_passed():
    assert not correction_overdue(ago(71), NOW, H, MAX) and correction_overdue(ago(72), NOW, H, MAX)


# ------------------------------------------------------------------------------------------- the worker step

def inv(n=1, decided_hours_ago=30, status="rejected", **over):
    return {"invoice_id": f"IN{n}", "case_id": "C1", "vendor_id": "V1", "vendor_name": "Acme", "po_number": "PO-1001", "invoice_number": f"INV-{n}",
            "status": status, "decided_at": ago(decided_hours_ago), "created_at": ago(decided_hours_ago + 1), "decision_note": "wrong total", "issues": ["x"], **over}


def world(monkeypatch, invoices, events=(), email="sales@acme.com", case_status="open"):
    log = {"reminders": [], "alerts": [], "escalations": [], "events": []}
    monkeypatch.setattr(case_pipeline.settings, "INVOICE_CHASE_HOURS", float(H))
    monkeypatch.setattr(case_pipeline.settings, "INVOICE_MAX_CHASES", MAX)
    monkeypatch.setattr(case_pipeline.settings, "ESCALATE_AFTER_HOURS", float(ESC))
    monkeypatch.setattr(case_pipeline, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW.replace(tzinfo=tz) if tz else NOW)}))
    monkeypatch.setattr(case_pipeline.invoice_agent, "list_invoices", lambda status=None: [i for i in invoices if status in (None, i["status"])])
    monkeypatch.setattr(case_pipeline.invoice_agent, "get_invoices", lambda cid: invoices)
    monkeypatch.setattr(case_pipeline.operations_agent, "get_all_cases", lambda r=None: [{"case_id": "C1", "status": case_status}])
    monkeypatch.setattr(case_pipeline.operations_agent, "get_case_events", lambda cid: list(events))
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_all_vendors", lambda: [{"vendor_id": "V1", "email": email}])
    monkeypatch.setattr(case_pipeline.invoice_agent, "request_corrected_invoice",
                        lambda i, to, note, reminder=0: log["reminders"].append((i["invoice_number"], to, note, reminder)) or True)
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled", lambda cid, reason, team=None: log["alerts"].append((reason, team)))
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_escalation", lambda cid, what, hours, label=None: log["escalations"].append((what, label)))
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", lambda cid, t, **kw: log["events"].append((t, kw["payload"])))
    return log


def test_the_worker_reminds_the_supplier_with_the_original_note_and_the_reminder_number(monkeypatch):
    log = world(monkeypatch, [inv()])
    assert case_pipeline.chase_invoice_corrections() == {"reminded": 1, "alerted": 0, "escalated": 0}
    assert log["reminders"] == [("INV-1", "sales@acme.com", "wrong total", 1)]


def test_it_sends_the_second_reminder_only_after_a_day_and_counts_only_reminders_that_went_out(monkeypatch):
    events = [{"event_type": "invoice.chased", "created_at": ago(25), "payload": {"invoice_id": "in1", "sent": True, "reminder": 1}},
              {"event_type": "invoice.chased", "created_at": ago(24.5), "payload": {"invoice_id": "in1", "sent": False}}]   # a failed send does not count
    log = world(monkeypatch, [inv(decided_hours_ago=60)], events)
    assert case_pipeline.chase_invoice_corrections()["reminded"] == 1 and log["reminders"][0][3] == 2


def test_after_the_reminders_run_out_accounts_is_told_once_and_it_is_recorded(monkeypatch):
    events = [{"event_type": "invoice.chased", "created_at": ago(h), "payload": {"invoice_id": "in1", "sent": True}} for h in (60, 36)]
    log = world(monkeypatch, [inv(decided_hours_ago=90)], events)
    assert case_pipeline.chase_invoice_corrections()["alerted"] == 1
    assert log["alerts"][0][1] == "invoice" and "has not sent a corrected invoice for INV-1" in log["alerts"][0][0] and "2 reminder(s)" in log["alerts"][0][0]
    assert ("invoice.correction_overdue", {"invoice_id": "IN1", "reminders": 2}) in log["events"]


def test_if_accounts_was_told_and_nothing_happened_the_admin_is_told_once(monkeypatch):
    events = [{"event_type": "invoice.chased", "created_at": ago(h), "payload": {"invoice_id": "in1", "sent": True}} for h in (100, 76)]
    events.append({"event_type": "invoice.correction_overdue", "created_at": ago(30), "payload": {"invoice_id": "IN1"}})
    log = world(monkeypatch, [inv(decided_hours_ago=130)], events)
    assert case_pipeline.chase_invoice_corrections()["escalated"] == 1 and log["escalations"][0][0] == "A supplier still has not sent a corrected invoice"
    assert any(t == "escalation.sent" and p["kind"] == "invoice_correction" and p["ref"] == "in1" for t, p in log["events"])
    events.append({"event_type": "escalation.sent", "created_at": ago(1), "payload": {"kind": "invoice_correction", "ref": "in1"}})
    log2 = world(monkeypatch, [inv(decided_hours_ago=130)], events)
    assert case_pipeline.chase_invoice_corrections() == {"reminded": 0, "alerted": 0, "escalated": 0} and log2["escalations"] == []


def test_a_corrected_invoice_arriving_stops_the_chasing(monkeypatch):
    newer = inv(2, decided_hours_ago=0, status="on_hold", decided_at=None, created_at=ago(5))
    log = world(monkeypatch, [inv(1, decided_hours_ago=30), newer])
    assert case_pipeline.chase_invoice_corrections() == {"reminded": 0, "alerted": 0, "escalated": 0} and log["reminders"] == []


def test_a_closed_case_is_never_chased(monkeypatch):
    log = world(monkeypatch, [inv()], case_status="closed")
    assert case_pipeline.chase_invoice_corrections() == {"reminded": 0, "alerted": 0, "escalated": 0} and log["reminders"] == []


def test_a_supplier_with_no_email_goes_straight_to_accounts_instead_of_failing_every_tick(monkeypatch):
    log = world(monkeypatch, [inv()], email=None)
    assert case_pipeline.chase_invoice_corrections()["alerted"] == 1 and log["reminders"] == []


def test_nothing_rejected_means_nothing_to_do(monkeypatch):
    log = world(monkeypatch, [inv(status="matched")])
    assert case_pipeline.chase_invoice_corrections() == {"reminded": 0, "alerted": 0, "escalated": 0} and log["events"] == []


# ------------------------------------------------------------------------------------------- the reminder email

def test_a_reminder_says_so_in_the_subject_and_body_and_is_recorded_as_a_chase(monkeypatch):
    sent, events = [], []
    monkeypatch.setattr(invoice_agent.email_client, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(invoice_agent.operations_agent, "publish_event", lambda cid, t, **kw: events.append((t, kw["payload"])))
    invoice = {"invoice_id": "i1", "case_id": "f8196120-e653-4ff2-ab68-b0af5dc70e7a", "vendor_name": "Acme", "invoice_number": "INV-9", "po_number": "PO-1001",
               "issues": ["Invoice total 120,000.00 differs from the purchase order total 95,000.00."]}
    assert invoice_agent.request_corrected_invoice(invoice, "sales@acme.com", None, reminder=2) is True
    to, subject, body = sent[0]
    assert subject.startswith("[OA-f8196120") and "Reminder:" in subject and "Reminder 2: we are still waiting" in body and "differs from the purchase order total" in body
    assert events == [("invoice.chased", {"invoice_id": "i1", "vendor": "Acme", "sent": True, "reminder": 2, "reason": None})]


# ------------------------------------------------------------------------------------------- Accounts' queue

def test_accounts_see_an_invoice_whose_supplier_has_gone_quiet_as_urgent():
    cases = [{"case_id": "C1", "case_number": "REQ-2026-0002", "items_summary": "Extinguishers", "stage": "po_issued", "status": "open", "updated_at": NOW}]
    quiet = inv(decided_hours_ago=80)
    result = build_my_work("acc", lambda p: p == "invoices:decide", [], cases, [], [quiet], [], NOW, chase_hours=H, max_chases=MAX)
    item = result["queues"][0]["items"][0]
    assert item["urgent"] and "has not sent a corrected invoice after 2 reminder(s)" in item["detail"] and item["title"].startswith("REQ-2026-0002")


def test_it_is_not_shown_while_the_supplier_still_has_time_or_has_already_answered():
    cases = [{"case_id": "C1", "case_number": "REQ-2026-0002", "items_summary": "x", "stage": "po_issued", "status": "open", "updated_at": NOW}]
    fresh = build_my_work("acc", lambda p: p == "invoices:decide", [], cases, [], [inv(decided_hours_ago=30)], [], NOW, chase_hours=H, max_chases=MAX)
    assert fresh["queues"][0]["items"] == []
    answered = [inv(1, decided_hours_ago=80), inv(2, decided_hours_ago=0, status="on_hold", decided_at=None, created_at=ago(5), issues=[], total_amount=1.0)]
    result = build_my_work("acc", lambda p: p == "invoices:decide", [], cases, [], answered, [], NOW, chase_hours=H, max_chases=MAX)
    assert [i["id"] for i in result["queues"][0]["items"]] == ["invoice:IN2"]        # only the new invoice that waits for the goods
