import os

for key, value in {
    "SQL_SERVER": "test",
    "SQL_DATABASE": "test",
    "SQL_DRIVER": "test",
    "SQL_TRUSTED_CONNECTION": "yes",
    "JWT_SECRET": "test-secret",
}.items():
    os.environ.setdefault(key, value)

from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402

from app.agents import delivery_agent  # noqa: E402
from app.core.delivery_policy import next_delivery_action  # noqa: E402
from app.core.exceptions import DeliveryAlreadyConfirmed  # noqa: E402
from app.orchestrator import case_pipeline  # noqa: E402

NOW = datetime(2026, 10, 10, 12, 0)
CASE = "3f2b8c1a-1111-4222-8333-444455556666"


def delivery(expected=date(2026, 10, 5), chases=0, last_h_ago=None, escalated=False, email="s@acme.com"):
    return {
        "purchase_order_id": "po-id", "po_number": "PO-1001", "case_id": CASE,
        "vendor_name": "Acme", "vendor_email": email, "expected_delivery_date": expected,
        "chase_count": chases,
        "last_chased_at": NOW - timedelta(hours=last_h_ago) if last_h_ago is not None else None,
        "escalated_at": NOW if escalated else None,
    }


def decide(d):
    return next_delivery_action(d, NOW, chase_interval_hours=24, max_chases=2)


# ---------- policy ----------

def test_not_late_yet_does_nothing():
    assert decide(delivery(expected=date(2026, 10, 10))) == "wait"  # due today is not late
    assert decide(delivery(expected=date(2026, 10, 20))) == "wait"


def test_first_day_late_chases_immediately():
    assert decide(delivery()) == "chase"


def test_waits_between_chases():
    assert decide(delivery(chases=1, last_h_ago=5)) == "wait"
    assert decide(delivery(chases=1, last_h_ago=25)) == "chase"


def test_escalates_only_after_the_last_chase_has_had_time():
    assert decide(delivery(chases=2, last_h_ago=5)) == "wait"
    assert decide(delivery(chases=2, last_h_ago=25)) == "escalate"


def test_escalates_once_not_repeatedly():
    assert decide(delivery(chases=2, last_h_ago=99, escalated=True)) == "wait"


# ---------- pipeline ----------

def _stub(monkeypatch, deliveries, chase_ok=True):
    log = {"chased": [], "escalated": [], "stages": [], "alerts": []}
    monkeypatch.setattr(case_pipeline.delivery_agent, "get_open_deliveries", lambda: deliveries)
    monkeypatch.setattr(case_pipeline.delivery_agent, "chase_vendor",
                        lambda d: log["chased"].append(d["po_number"]) or chase_ok)
    monkeypatch.setattr(case_pipeline.delivery_agent, "mark_escalated",
                        lambda d: log["escalated"].append(d["po_number"]))
    monkeypatch.setattr(case_pipeline.operations_agent, "set_stage", lambda cid, s: log["stages"].append(s))
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled",
                        lambda cid, reason, team=None: log["alerts"].append(reason))
    # the tick compares against the real clock, so make every test PO clearly overdue/not
    return log


def test_overdue_po_is_chased_automatically(monkeypatch):
    log = _stub(monkeypatch, [delivery(expected=date(2020, 1, 1))])
    assert case_pipeline.track_deliveries() == {"chased": 1, "escalated": 0}
    assert log["chased"] == ["PO-1001"] and log["alerts"] == []


def test_future_po_is_left_alone(monkeypatch):
    log = _stub(monkeypatch, [delivery(expected=date(2999, 1, 1))])
    assert case_pipeline.track_deliveries() == {"chased": 0, "escalated": 0}
    assert log["chased"] == []


def test_persistently_late_po_alerts_a_human_once(monkeypatch):
    log = _stub(monkeypatch, [delivery(expected=date(2020, 1, 1), chases=2, last_h_ago=999999)])
    # last_chased_at is relative to NOW (2026); the real clock is later, so the interval has passed
    assert case_pipeline.track_deliveries() == {"chased": 0, "escalated": 1}
    assert log["escalated"] == ["PO-1001"] and log["stages"] == ["delivery_late"]
    assert "PO-1001" in log["alerts"][0] and "Acme" in log["alerts"][0]


def test_failed_chase_is_not_counted(monkeypatch):
    log = _stub(monkeypatch, [delivery(expected=date(2020, 1, 1))], chase_ok=False)
    assert case_pipeline.track_deliveries() == {"chased": 0, "escalated": 0}


def test_confirming_receipt_stops_the_chase_and_moves_the_case_on(monkeypatch):
    stages = []
    monkeypatch.setattr(case_pipeline.delivery_agent, "confirm_received",
                        lambda cid, by, note, items=None: {"delivery_status": "delivered"})
    monkeypatch.setattr(case_pipeline.operations_agent, "set_stage", lambda cid, s: stages.append(s))
    monkeypatch.setattr(case_pipeline.invoice_agent, "get_invoices", lambda cid: [])
    monkeypatch.setattr(case_pipeline.delivery_agent, "get_delivery",
                        lambda cid: {"delivery_status": "delivered"})
    assert case_pipeline.confirm_delivery(CASE, "ravi", None)["delivery_status"] == "delivered"
    assert stages == ["delivered"]


# ---------- agent ----------

def test_chase_email_names_the_po_and_date(monkeypatch):
    sent, marked, events = [], [], []
    monkeypatch.setattr(delivery_agent.email_client, "send_email",
                        lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(delivery_agent.purchase_order_repository, "mark_chased", lambda pid: marked.append(pid))
    monkeypatch.setattr(delivery_agent.operations_agent, "publish_event",
                        lambda cid, t, **kw: events.append(t))
    assert delivery_agent.chase_vendor(delivery()) is True
    to, subject, body = sent[0]
    assert to == "s@acme.com" and "PO-1001" in subject and "05 Oct 2026" in body
    assert marked == ["po-id"] and events == ["delivery.chased"]


def test_vendor_without_email_cannot_be_chased(monkeypatch):
    marked = []
    monkeypatch.setattr(delivery_agent.purchase_order_repository, "mark_chased", lambda pid: marked.append(pid))
    assert delivery_agent.chase_vendor(delivery(email=None)) is False
    assert marked == []


def test_smtp_failure_is_not_counted_as_a_chase(monkeypatch):
    marked = []

    def boom(*a):
        raise OSError("smtp down")

    monkeypatch.setattr(delivery_agent.email_client, "send_email", boom)
    monkeypatch.setattr(delivery_agent.purchase_order_repository, "mark_chased", lambda pid: marked.append(pid))
    assert delivery_agent.chase_vendor(delivery()) is False
    assert marked == []


def test_receipt_cannot_be_confirmed_twice(monkeypatch):
    row = type("Row", (), {"purchase_order_id": "po-id", "po_number": 1001, "delivery_status": "pending", "items_json": "[{\"description\": \"x\", \"quantity\": 1}]", "received_json": None})()
    monkeypatch.setattr(delivery_agent.purchase_order_repository, "find_purchase_order_by_case_id",
                        lambda cid: row)
    monkeypatch.setattr(delivery_agent.purchase_order_repository, "mark_delivered",
                        lambda pid, by, note: False)
    monkeypatch.setattr(delivery_agent.purchase_order_repository, "append_receipt", lambda *a: True)
    with pytest.raises(DeliveryAlreadyConfirmed):
        delivery_agent.confirm_received(CASE, "ravi", None)
