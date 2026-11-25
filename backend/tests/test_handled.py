"""My work: what each team finished recently."""

from datetime import datetime, timedelta

from app.core.handled import LIMIT_PER_QUEUE, recent_handled
from app.core.my_work import build_my_work

NOW = datetime(2026, 3, 2, 12)
CASES = {"aaa": {"case_id": "AAA", "case_number": "REQ-1", "items_summary": "8 racks", "status": "open", "stage": "delivered", "requester_id": "ann"}}


def ev(kind, hours_ago, case_id="AAA", **payload):
    return {"case_id": case_id, "event_type": kind, "payload": payload, "created_at": NOW - timedelta(hours=hours_ago)}


def test_only_what_a_person_did_and_only_recent_and_newest_first():
    events = [
        ev("approval.approved", 3, decided_by="mgr"),
        ev("approval.rejected", 1, decided_by="boss"),
        ev("approval.approved", 30, decided_by="mgr"),          # too old
        ev("approval.auto_approved", 1),                        # the agent, not a person
        ev("vendor.selected", 1, vendor_id="x"),                # automatic choice: nobody named
    ]
    got = recent_handled(events, CASES, NOW, 24, {"approval", "vendor"})
    assert [(h["what"], h["by"]) for h in got["approval"]] == [("Rejected", "boss"), ("Approved", "mgr")]
    assert got["vendor"] == []
    assert got["approval"][0]["title"] == "REQ-1 · 8 racks" and got["approval"][0]["link"] == "/cases/AAA"


def test_each_team_only_gets_its_own_kind_and_unseen_queues_are_dropped():
    events = [ev("delivery.received", 2, received_by="recv"), ev("invoice.approved", 2, decided_by="acc"), ev("delivery.dispute_handled", 1, by="recv")]
    got = recent_handled(events, CASES, NOW, 24, {"delivery"})
    assert list(got) == ["delivery"] and [h["what"] for h in got["delivery"]] == ["Followed up with the requester", "Marked as received"]


def test_a_long_list_is_capped_and_ids_are_unique():
    events = [ev("approval.approved", 0.01 * (i + 1), decided_by="m") for i in range(30)]
    got = recent_handled(events, CASES, NOW, 24, {"approval"})["approval"]
    assert len(got) == LIMIT_PER_QUEUE and len({h["id"] for h in got}) == LIMIT_PER_QUEUE


def test_it_appears_under_the_queue_and_does_not_count_as_waiting():
    work = build_my_work("recv", lambda p: p == "delivery:confirm", approvals=[], cases=list(CASES.values()), deliveries=[], invoices=[], stock=[], now=NOW,
                         handled_events=[ev("delivery.received", 2, received_by="recv")], handled_hours=24)
    q = work["queues"][0]
    assert work["total"] == 0 and q["items"] == [] and q["handled"][0]["what"] == "Marked as received"


def test_default_is_an_empty_list():
    work = build_my_work("recv", lambda p: p == "delivery:confirm", approvals=[], cases=[], deliveries=[], invoices=[], stock=[], now=NOW)
    assert work["queues"][0]["handled"] == []
