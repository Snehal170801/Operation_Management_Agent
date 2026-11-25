"""Urgent requests ("needed by Friday"): chased harder, never skipped, never approved blindly."""

from datetime import date, datetime, timedelta

import pytest

from app.agents import approval_agent, operations_agent, purchase_agent, vendor_agent
from app.controllers import approval_controller
from app.core import urgency
from app.core.config import settings
from app.core.escalation import due_escalations
from app.orchestrator import case_pipeline

from .fake_world import World, now, standard_world

TODAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 9, 0)


# ---- the rules ----

def test_what_the_person_typed_wins_over_what_the_ai_read():
    assert urgency.resolve(date(2026, 10, 20), False, "2026-10-08", True, TODAY, 3) == (date(2026, 10, 20), False)
    assert urgency.resolve(None, False, "2026-10-20", False, TODAY, 3) == (date(2026, 10, 20), False)
    assert urgency.resolve(None, True, None, None, TODAY, 3) == (None, True)
    assert urgency.resolve(None, False, None, True, TODAY, 3) == (None, True)         # the text said "urgent"
    assert urgency.resolve(None, False, None, "yes", TODAY, 3) == (None, False)       # only a real true counts


def test_a_date_close_enough_makes_it_urgent_and_nonsense_dates_are_ignored():
    assert urgency.resolve(date(2026, 10, 8), False, None, None, TODAY, 3) == (date(2026, 10, 8), True)
    assert urgency.resolve(date(2026, 10, 9), False, None, None, TODAY, 3) == (date(2026, 10, 9), False)
    assert urgency.resolve(None, False, "2026-09-01", None, TODAY, 3) == (None, False)        # in the past
    assert urgency.resolve(None, False, "2030-01-01", None, TODAY, 3) == (None, False)        # years away
    assert urgency.resolve(None, False, "next friday", None, TODAY, 3) == (None, False)       # not a date


def test_suppliers_get_less_time_when_it_is_urgent_and_never_more_than_a_share_of_what_is_left():
    assert urgency.quote_deadline_hours(False, None, NOW, 48, 12) == 48
    assert urgency.quote_deadline_hours(True, None, NOW, 48, 12) == 12
    assert urgency.quote_deadline_hours(True, date(2026, 10, 6), NOW, 48, 12) == 12                                    # plenty of time left: the urgent limit applies
    assert urgency.quote_deadline_hours(False, date(2026, 10, 7), NOW, 48, 12) == pytest.approx(0.4 * 63, abs=0.1)    # a date caps even a normal request
    assert urgency.quote_deadline_hours(True, date(2026, 10, 5), NOW, 48, 12) == pytest.approx(max(2, 0.4 * 15), abs=0.1)
    assert urgency.quote_deadline_hours(True, date(2026, 10, 5), datetime(2026, 10, 5, 23, 0), 48, 12) == 2           # never under two hours
    assert urgency.quote_deadline_hours(False, date(2027, 1, 1), NOW, 48, 12) == 48


def test_the_waits_are_shorter_only_for_urgent_requests():
    assert urgency.pick(False, 24, 4) == 24 and urgency.pick(True, 24, 4) == 4 and urgency.pick(True, 2, 4) == 2


def test_can_a_supplier_deliver_in_time():
    assert urgency.meets(5, date(2026, 10, 10), TODAY) is True and urgency.meets(6, date(2026, 10, 10), TODAY) is False
    assert urgency.meets(None, date(2026, 10, 10), TODAY) is None and urgency.meets(5, None, TODAY) is None


def test_the_line_for_the_supplier():
    assert urgency.request_note(False, None) == ""
    assert "URGENT" in urgency.request_note(True, date(2026, 10, 9)) and "09 Oct 2026" in urgency.request_note(True, date(2026, 10, 9))
    assert "URGENT" not in urgency.request_note(False, date(2026, 10, 20))


def test_an_urgent_case_is_escalated_sooner():
    case = {"case_id": "AAA", "case_number": "R1", "stage": "sourcing_stalled", "status": "open", "updated_at": NOW - timedelta(hours=6), "items_summary": "x"}
    assert due_escalations(NOW, 24, [], [case], [], set()) == []
    found = due_escalations(NOW, 24, [], [case], [], set(), {"aaa"}, 4)
    assert len(found) == 1 and found[0]["hours_waiting"] == 6.0
    assert due_escalations(NOW, 24, [], [case], [], set(), {"zzz"}, 4) == []                          # a different case is not urgent


# ---- the flow ----

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def rfq_mails(w):
    return [m for m in w.sent if "Request for quotation" in m[1] and "Reminder" not in m[2]]


def test_an_urgent_request_asks_suppliers_sooner_and_says_so(w):
    w.teach("urgently 50 cameras", [{"description": "CCTV camera", "quantity": 50}], urgent=True)
    case_id = w.submit("urgently 50 cameras")
    assert purchase_agent.get_purchase_request(case_id)["urgent"] is True
    mails = rfq_mails(w)
    assert len(mails) == 3 and all(m[1].endswith("URGENT - Request for quotation") and "This is URGENT" in m[2] for m in mails)
    deadlines = {r.deadline_at for r in w.rfqs if r.case_id == case_id}
    assert all(d - now() <= timedelta(hours=12, minutes=1) for d in deadlines)


def test_the_form_date_beats_the_text_and_marks_a_close_date_urgent(w):
    needed = date.today() + timedelta(days=2)
    case_id = case_pipeline.start_case("ravi@x.co", "50 cameras", needed_by=needed)
    request = purchase_agent.get_purchase_request(case_id)
    assert request["needed_by"] == needed and request["urgent"] is True
    assert all(f"{needed:%d %b %Y}" in m[2] for m in rfq_mails(w))
    ev = next(e for e in operations_agent.get_case_events(case_id) if e["event_type"] == "purchase_request.created")
    assert ev["payload"]["urgent"] is True and ev["payload"]["needed_by"] == needed.isoformat()


def test_an_ordinary_request_is_untouched(w):
    case_id = w.submit("50 cameras")
    assert purchase_agent.get_purchase_request(case_id)["urgent"] is False
    assert all("URGENT" not in m[1] and "URGENT" not in m[2] for m in rfq_mails(w))


def silent_for(w, case_id, hours):
    for r in w.rfqs:
        if r.case_id == case_id:
            r.sent_at = r.last_contacted_at = r.sent_at - timedelta(hours=hours)


def test_silent_suppliers_are_reminded_sooner_when_urgent(w):
    w.teach("urgently 50 cameras", [{"description": "CCTV camera", "quantity": 50}], urgent=True)
    urgent_case = w.submit("urgently 50 cameras")
    ordinary_case = w.submit("50 cameras")
    for c in (urgent_case, ordinary_case):
        silent_for(w, c, 5)                              # five hours: past the urgent interval (4 h), not the normal one (24 h)
    assert case_pipeline.advance_sourcing(urgent_case) == "remind"
    assert case_pipeline.advance_sourcing(ordinary_case) == "wait"


def test_a_quote_that_arrives_too_late_is_marked_and_needs_a_person(w):
    needed = date.today() + timedelta(days=4)
    case_id = case_pipeline.start_case("ravi@x.co", "50 cameras", needed_by=needed)
    for name, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30", "Globex": "Total Rs 45,000. Delivery 7 days. Terms: net 30"}.items():
        w.reply(case_id, name, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval"                      # cheap and reliable, but it cannot arrive in time
    pending = next(a for a in approval_agent.get_approvals(case_id=case_id) if a["status"] == "pending")
    assert any("misses the date it is needed by" in r for r in pending["reasons"])
    review = approval_controller.get_review(pending["approval_id"])
    assert review.needed_by == needed and not review.urgent and all("Too late" in o.tags for o in review.options)


def test_a_quote_that_arrives_in_time_is_still_approved_automatically(w):
    needed = date.today() + timedelta(days=10)
    case_id = case_pipeline.start_case("ravi@x.co", "50 cameras", needed_by=needed)
    for name, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30", "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, name, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "po_issued"


def test_the_ranking_is_told_the_date_and_who_can_meet_it(w, monkeypatch):
    seen = {}
    real = vendor_agent.azure_openai_client.ask_json

    def spy(system_prompt, user_prompt, temperature=0.1):
        if "Rank ALL the vendors" in system_prompt:
            seen["system"], seen["user"] = system_prompt, user_prompt
        return real(system_prompt, user_prompt, temperature)
    monkeypatch.setattr(vendor_agent.azure_openai_client, "ask_json", spy)
    needed = date.today() + timedelta(days=6)
    case_id = case_pipeline.start_case("ravi@x.co", "50 cameras", needed_by=needed)
    for name, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30", "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, name, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    assert f"needed by {needed:%d %b %Y}" in seen["system"] and "must rank below every vendor who can" in seen["system"]
    assert "'meets_needed_by': False" in seen["user"] and "'meets_needed_by': True" in seen["user"]


def test_an_urgent_approval_is_reminded_sooner_and_leads_my_work(w):
    needed = date.today() + timedelta(days=2)
    urgent_case = case_pipeline.start_case("ravi@x.co", "50 cameras", needed_by=needed)
    ordinary_case = w.submit("50 cameras")
    for case_id in (urgent_case, ordinary_case):
        for name, text in {"Acme": "Total Rs 90,000. Delivery 1 days. Terms: net 30", "Globex": "Total Rs 95,000. Delivery 1 days. Terms: net 30"}.items():
            w.reply(case_id, name, text)
        w.expire_quote_deadline(case_id)
    w.tick()
    pending = {a.case_id: a for a in w.approvals if a.status == "pending"}
    assert set(pending) == {urgent_case, ordinary_case}
    for a in pending.values():
        a.created_at -= timedelta(hours=5)                                 # five hours old: urgent interval is 4 h, normal is 24 h
    assert case_pipeline.remind_pending_approvals() == 1
    assert pending[urgent_case].reminder_count == 1 and pending[ordinary_case].reminder_count == 0

    from app.core.my_work import build_my_work
    cases = operations_agent.get_all_cases(None)
    work = build_my_work("approver", lambda p: p == "approvals:write", approvals=approval_agent.get_approvals(status="pending"), cases=cases,
                         deliveries=[], invoices=[], stock=[], now=now())
    first = work["queues"][0]["items"][0]
    assert first["urgent"] and first["title"].startswith("URGENT by ")


def test_the_times_can_be_changed_in_configure(w, monkeypatch):
    monkeypatch.setattr(settings, "URGENT_REMINDER_HOURS", 1)
    w.teach("urgently 50 cameras", [{"description": "CCTV camera", "quantity": 50}], urgent=True)
    case_id = w.submit("urgently 50 cameras")
    silent_for(w, case_id, 2)
    assert case_pipeline.advance_sourcing(case_id) == "remind"
