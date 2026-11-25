import os

for key, value in {
    "SQL_SERVER": "test",
    "SQL_DATABASE": "test",
    "SQL_DRIVER": "test",
    "SQL_TRUSTED_CONNECTION": "yes",
    "JWT_SECRET": "test-secret",
}.items():
    os.environ.setdefault(key, value)

from datetime import datetime, timedelta  # noqa: E402

from app.core.sourcing_policy import next_sourcing_action  # noqa: E402
from app.orchestrator import case_pipeline, worker  # noqa: E402

NOW = datetime(2026, 10, 10, 12, 0)


def rfq(rfq_id, status="sent", deadline_in_h=48, contacted_h_ago=0, reminders=0):
    return {
        "rfq_id": rfq_id,
        "status": status,
        "deadline_at": NOW + timedelta(hours=deadline_in_h),
        "last_contacted_at": NOW - timedelta(hours=contacted_h_ago),
        "reminder_count": reminders,
    }


def decide(rfqs, quotes):
    return next_sourcing_action(rfqs, quotes, NOW, reminder_interval_hours=24, max_reminders=2)


def test_everyone_replied_ranks_immediately():
    assert decide([rfq("a", "replied"), rfq("b", "replied")], 2) == ("rank", [])


def test_waits_while_vendors_still_have_time():
    assert decide([rfq("a", "replied"), rfq("b")], 1) == ("wait", [])


def test_deadline_passed_with_some_quotes_ranks():
    assert decide([rfq("a", "replied", deadline_in_h=-1), rfq("b", deadline_in_h=-1)], 1) == ("rank", [])


def test_deadline_passed_with_no_quotes_needs_a_human():
    assert decide([rfq("a", deadline_in_h=-1)], 0) == ("stalled", [])


def test_no_vendors_invited_needs_a_human():
    assert decide([], 0) == ("stalled", [])


def test_silent_vendors_are_chased_after_interval():
    assert decide([rfq("a", contacted_h_ago=25), rfq("b", "replied")], 1) == ("remind", ["a"])


def test_reminders_stop_at_the_cap():
    assert decide([rfq("a", contacted_h_ago=25, reminders=2)], 0) == ("wait", [])


def _stub_pipeline(monkeypatch, sufficient, invited=("Vendor A",)):
    calls = []
    stalled = []
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled",
                        lambda cid, reason, team=None: stalled.append(cid))
    monkeypatch.setattr(case_pipeline, "_stalled_calls", stalled, raising=False)
    monkeypatch.setattr(case_pipeline.operations_agent, "create_case", lambda requester_id: "c1")
    monkeypatch.setattr(case_pipeline.purchase_agent, "create_purchase_request", lambda **kw: None)
    monkeypatch.setattr(case_pipeline.purchase_agent, "get_purchase_request",
                        lambda cid: {"items": [{"description": "Camera", "quantity": 50}]})
    monkeypatch.setattr(case_pipeline.procurement_agent, "check_stock",
                        lambda case_id: {"sufficient": sufficient})
    monkeypatch.setattr(case_pipeline.vendor_agent, "send_rfqs",
                        lambda cid, items, **kw: calls.append((cid, items)) or list(invited))
    return calls


def test_no_reachable_vendor_alerts_a_human(monkeypatch):
    _stub_pipeline(monkeypatch, sufficient=False, invited=())
    case_pipeline.start_case("ravi", "need 50 cameras")
    assert case_pipeline._stalled_calls == ["c1"]


def test_reachable_vendors_do_not_alert_anyone(monkeypatch):
    _stub_pipeline(monkeypatch, sufficient=False)
    case_pipeline.start_case("ravi", "need 50 cameras")
    assert case_pipeline._stalled_calls == []


def test_deadline_with_no_quotes_stalls_and_alerts(monkeypatch):
    alerts, stages = [], []
    monkeypatch.setattr(case_pipeline.purchase_agent, "get_purchase_request", lambda cid: {"items": [], "urgent": False, "needed_by": None})
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_rfqs",
                        lambda cid: [{"rfq_id": "a", "status": "sent",
                                      "deadline_at": datetime(2020, 1, 1),
                                      "last_contacted_at": datetime(2020, 1, 1), "reminder_count": 0}])
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_quotes", lambda cid: [])
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", lambda *a, **k: None)
    monkeypatch.setattr(case_pipeline.operations_agent, "set_stage", lambda cid, s: stages.append(s))
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled",
                        lambda cid, reason, team=None: alerts.append(cid))
    assert case_pipeline.advance_sourcing("c1") == "stalled"
    assert stages == ["sourcing_stalled"] and alerts == ["c1"]


def test_enough_stock_sends_no_rfqs(monkeypatch):
    calls = _stub_pipeline(monkeypatch, sufficient=True)
    case_pipeline.start_case("ravi", "need 50 cameras")
    assert calls == []


def test_not_enough_stock_sends_rfqs_automatically(monkeypatch):
    calls = _stub_pipeline(monkeypatch, sufficient=False)
    case_pipeline.start_case("ravi", "need 50 cameras")
    assert calls == [("c1", [{"description": "Camera", "quantity": 50}])]


def test_advance_sourcing_ranks_when_ready(monkeypatch):
    ranked = []
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_rfqs",
                        lambda cid: [{"rfq_id": "a", "status": "replied",
                                      "deadline_at": datetime(2999, 1, 1),
                                      "last_contacted_at": datetime(2026, 1, 1), "reminder_count": 0}])
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_quotes", lambda cid: [{"price": 1}])
    monkeypatch.setattr(case_pipeline, "rank_and_review", lambda cid, negotiate=False: ranked.append((cid, negotiate)))
    assert case_pipeline.advance_sourcing("c1") == "rank"
    assert ranked == [("c1", True)]                              # the first ranking of a round may negotiate (when it is switched on)


def test_worker_parks_a_failing_case_instead_of_retrying_forever(monkeypatch):
    stages, events = [], []
    monkeypatch.setattr(worker.case_repository, "find_open_case_ids_by_stage", lambda s: ["c1", "c2"])

    def advance(cid):
        if cid == "c1":
            raise RuntimeError("LLM down")

    monkeypatch.setattr(worker.case_pipeline, "advance_sourcing", advance)
    monkeypatch.setattr(worker.operations_agent, "set_stage", lambda cid, s: stages.append((cid, s)))
    monkeypatch.setattr(worker.operations_agent, "publish_event",
                        lambda cid, t, **kw: events.append((cid, t)))
    alerts = []
    monkeypatch.setattr(worker.notification_agent, "notify_case_stalled",
                        lambda cid, reason, team=None: alerts.append(cid))
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda handler: 0)
    monkeypatch.setattr(worker.case_pipeline, "remind_pending_approvals", lambda: 0)

    worker.run_once()  # must not raise, and c2 must still be processed
    assert stages == [("c1", "sourcing_stalled")]
    assert events == [("c1", "worker.error")]
    assert alerts == ["c1"]
