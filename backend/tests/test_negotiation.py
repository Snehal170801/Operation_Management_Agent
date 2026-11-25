"""Negotiation: the best supplier is asked once for a better price; a lower reply is taken, anything else keeps the original; approval still decides."""

from datetime import datetime, timedelta

import pytest

from app.core import negotiation as ng, tunables
from app.core.config import settings
from app.orchestrator import case_pipeline

from .fake_world import now, standard_world

T0 = datetime(2026, 10, 9, 10, 0)


def ev(kind, **payload):
    return {"event_type": kind, "payload": payload, "created_at": T0}


# ---- the rules ----------------------------------------------------------------------------------------------------------------------------

def test_a_supplier_is_asked_only_when_switched_on_there_is_a_price_an_address_and_no_earlier_ask():
    assert ng.should_ask(True, [], 40000.0, "a@x.co") is None
    assert ng.should_ask(False, [], 40000.0, "a@x.co") == "off"
    assert ng.should_ask(True, [], None, "a@x.co") == "no price" and ng.should_ask(True, [], 0, "a@x.co") == "no price"
    assert ng.should_ask(True, [], 40000.0, "  ") == "no e-mail address" and ng.should_ask(True, [], 40000.0, None) == "no e-mail address"
    assert ng.should_ask(True, [ev(ng.ASKED, vendor_id="v")], 40000.0, "a@x.co") == "already asked"


def test_a_new_round_of_quotes_may_negotiate_again_but_the_same_round_never_twice():
    asked = ev(ng.ASKED, vendor_id="v", original_price=1)
    assert ng.asked_this_round([asked])["vendor_id"] == "v"
    assert ng.asked_this_round([asked, ev("sourcing.restarted")]) is None
    assert ng.asked_this_round([asked, ev("sourcing.restarted"), ev(ng.ASKED, vendor_id="w")])["vendor_id"] == "w"


def test_only_a_lower_sane_price_is_an_improvement():
    assert ng.verdict(40000, 36000) == "improved"
    assert ng.verdict(40000, 40000) == "same_or_higher" and ng.verdict(40000, 45000) == "same_or_higher"
    assert ng.verdict(40000, 1000) == "suspicious"                                     # under a fifth: almost surely a misreading
    assert ng.verdict(40000, None) == "unreadable" and ng.verdict(None, 100) == "unreadable" and ng.verdict(40000, 0) == "unreadable"


def test_the_wait_ends_after_the_set_hours():
    assert not ng.is_due(T0, T0 + timedelta(hours=23), 24) and ng.is_due(T0, T0 + timedelta(hours=24), 24) and not ng.is_due(None, T0, 24)


def test_the_message_says_what_is_asked_and_that_silence_keeps_the_quote():
    text = ng.message("Acme", [{"description": "Camera", "quantity": 5}], 40000.0, 24)
    assert "40,000.00" in text and "Camera x 5" in text and "better total price" in text and "stands as it is" in text and "24 hours" in text
    assert "saves 4,000.00, 10.0%" in ng.summary(40000.0, 36000.0)


# ---- through the pipeline -----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    monkeypatch.setattr(settings, "NEGOTIATE_ENABLED", True)
    monkeypatch.setattr(settings, "NEGOTIATE_WAIT_HOURS", 24.0)
    return standard_world(monkeypatch)


def quoted(w, prices=(("Acme", "40,000"), ("Globex", "45,000"), ("Initech", "47,000"))):
    case_id = w.submit("50 cameras")
    for name, price in prices:
        assert w.reply(case_id, name, f"Total Rs {price}. Delivery 7 days. Terms: net 30") == "quoted"
    return case_id


def asked_events(w, case_id):
    return [e for e in w.events[case_id] if e.event_type == "negotiation.asked"]


def test_when_switched_on_the_best_supplier_is_asked_and_the_case_waits(w):
    case_id = quoted(w)
    assert w.stage(case_id) == "negotiating"
    asked = asked_events(w, case_id)
    assert len(asked) == 1 and asked[0].payload["vendor"] == "Acme" and asked[0].payload["original_price"] == 40000.0
    mail = next(m for m in w.sent if "improve your price" in m[1])
    assert mail[0] == "acme@vendor.com" and "40,000.00" in mail[2] and f"[OA-{case_id}]" in mail[1]
    assert not w.pos and not w.approvals                                                # nothing decided yet


def test_when_switched_off_it_goes_straight_to_approval_as_before(w, monkeypatch):
    monkeypatch.setattr(settings, "NEGOTIATE_ENABLED", False)
    case_id = quoted(w)
    assert w.stage(case_id) != "negotiating" and not asked_events(w, case_id) and not [m for m in w.sent if "improve your price" in m[1]]


def test_a_lower_reply_is_taken_and_the_order_goes_out_at_the_new_price(w):
    case_id = quoted(w)
    assert w.reply(case_id, "Acme", "Sure: Total Rs 36,000. Delivery 7 days. Terms: net 30") == "negotiated"
    improved = next(e for e in w.events[case_id] if e.event_type == "negotiation.improved")
    assert improved.payload["old_price"] == 40000.0 and improved.payload["new_price"] == 36000.0
    assert w.stage(case_id) == "po_issued" and w.pos[case_id].total_amount == 36000.0


def test_a_higher_or_equal_reply_keeps_the_original_and_is_not_recorded_as_a_quote(w):
    case_id = quoted(w)
    before = len([q for q in w.quotes if q.case_id == case_id])
    assert w.reply(case_id, "Acme", "Sorry, the price is now Total Rs 44,000. Delivery 7 days.") == "negotiation_kept"
    assert len([q for q in w.quotes if q.case_id == case_id]) == before
    assert w.pos[case_id].total_amount == 40000.0 and "negotiation.no_improvement" in w.event_types(case_id)


def test_a_refusal_keeps_the_original(w):
    case_id = quoted(w)
    assert w.reply(case_id, "Acme", "Sorry, we cannot go lower.") in ("negotiation_kept", "question")
    assert w.pos[case_id].total_amount == 40000.0 if case_id in w.pos else True


def test_a_suspiciously_low_reply_is_not_taken_and_the_vendor_team_is_told(w):
    case_id = quoted(w)
    assert w.reply(case_id, "Acme", "Total Rs 1,000. Delivery 7 days.") == "negotiation_kept"
    assert w.pos[case_id].total_amount == 40000.0
    assert [m for m in w.emails_to("manager@x.co") if "far below" in m[2] and "misreading" in m[2]]


def test_a_question_from_the_supplier_tells_the_team_and_the_wait_goes_on(w):
    case_id = quoted(w)
    assert w.reply(case_id, "Acme", "Which delivery date do you need?") == "question"
    assert w.stage(case_id) == "negotiating" and "quote.question" in w.event_types(case_id)


def test_silence_keeps_the_original_after_the_wait_and_the_case_moves_on(w):
    case_id = quoted(w)
    assert case_pipeline.track_negotiations() == 0 and w.stage(case_id) == "negotiating"             # not yet
    for e in w.events[case_id]:
        if e.event_type == "negotiation.asked":
            e.created_at = now() - timedelta(hours=25)
    assert case_pipeline.track_negotiations() == 1
    assert "negotiation.no_reply" in w.event_types(case_id) and w.stage(case_id) == "po_issued" and w.pos[case_id].total_amount == 40000.0
    assert case_pipeline.track_negotiations() == 0                                                  # and it never repeats


def test_another_suppliers_late_mail_during_the_wait_is_not_used(w):
    case_id = quoted(w)
    assert w.reply(case_id, "Globex", "Total Rs 30,000. Delivery 3 days.") == "not_accepting"
    assert w.stage(case_id) == "negotiating"


def test_the_approval_rules_still_decide_a_negotiated_price(w):
    case_id = quoted(w, prices=(("Acme", "900,000"), ("Globex", "950,000"), ("Initech", "970,000")))
    assert w.stage(case_id) == "negotiating"
    assert w.reply(case_id, "Acme", "Total Rs 850,000. Delivery 7 days. Terms: net 30") == "negotiated"
    assert w.stage(case_id) == "awaiting_approval" and not w.pos                                    # still too big for automatic approval


def test_it_asks_only_once_per_round_even_if_ranking_runs_again(w):
    case_id = quoted(w)
    w.reply(case_id, "Acme", "Total Rs 36,000. Delivery 7 days.")
    case_pipeline.rank_and_review(case_id, negotiate=True)                                          # (a repeat) must not ask again
    assert len(asked_events(w, case_id)) == 1 and len([m for m in w.sent if "improve your price" in m[1]]) == 1


def test_no_address_or_a_failed_send_skips_the_negotiation_and_the_case_goes_on(w, monkeypatch):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "Total Rs 40,000. Delivery 7 days. Terms: net 30")
    w.vendors[w.vendor_id("Acme")].email = None                                        # (their address is removed after they quoted)
    w.reply(case_id, "Globex", "Total Rs 45,000. Delivery 7 days. Terms: net 30")
    w.reply(case_id, "Initech", "Total Rs 47,000. Delivery 7 days. Terms: net 30")
    assert w.stage(case_id) != "negotiating" and not asked_events(w, case_id)
    assert any(e.event_type == "negotiation.skipped" for e in w.events[case_id]) and w.pos[case_id].total_amount == 40000.0


def test_a_failed_send_is_noted_and_the_case_goes_on(w, monkeypatch):
    real = case_pipeline.vendor_agent.email_client.send_email

    def flaky(to, subject, body, html=None):
        if "improve your price" in subject:
            raise RuntimeError("smtp down")
        return real(to, subject, body, html)
    monkeypatch.setattr(case_pipeline.vendor_agent.email_client, "send_email", flaky)
    case_id = quoted(w)
    skipped = [e for e in w.events[case_id] if e.event_type == "negotiation.skipped"]
    assert skipped and "could not be sent" in skipped[0].payload["reason"] and w.stage(case_id) != "negotiating"


def test_an_unexpected_failure_never_holds_the_case_back(w, monkeypatch):
    monkeypatch.setattr(case_pipeline.vendor_agent, "ask_better_price", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    case_id = quoted(w)
    assert w.stage(case_id) != "negotiating" and w.pos[case_id].total_amount == 40000.0


def test_a_cancelled_case_is_left_alone_by_the_timer(w):
    case_id = quoted(w)
    case_pipeline.cancel_case(case_id, "ravi@x.co", "not needed")
    for e in w.events[case_id]:
        if e.event_type == "negotiation.asked":
            e.created_at = now() - timedelta(hours=48)
    assert case_pipeline.track_negotiations() == 0 and w.cases[case_id].status == "closed"


def test_the_worker_runs_the_timer_every_pass(w, monkeypatch):
    from app.orchestrator import worker
    calls = []
    monkeypatch.setattr(case_pipeline, "track_negotiations", lambda: calls.append(1) or (_ for _ in ()).throw(RuntimeError("boom")))
    worker.run_once()
    assert calls == [1]


def test_the_settings_are_in_configure_off_by_default():
    keys = {t.key: t for t in tunables.CATALOG}
    assert tunables.DEFAULTS["NEGOTIATE_ENABLED"] is False and keys["NEGOTIATE_WAIT_HOURS"].group == "requests"
    assert tunables.validate({"NEGOTIATE_WAIT_HOURS": 6}) == {"NEGOTIATE_WAIT_HOURS": 6.0}
    with pytest.raises(tunables.InvalidSetting):
        tunables.validate({"NEGOTIATE_WAIT_HOURS": 0})


# ---- what the approver sees ---------------------------------------------------------------------------------------------------------------

def events_of(*kinds_and_payloads):
    return [ev(kind, **payload) for kind, payload in kinds_and_payloads]


def test_the_note_says_what_came_of_the_negotiation():
    asked = (ng.ASKED, {"vendor": "Acme", "original_price": 40000.0})
    assert ng.note([]) is None and ng.note(events_of(("case.created", {}))) is None
    waiting = ng.note(events_of(asked))
    assert waiting["outcome"] == "waiting" and "still waiting" in waiting["text"]
    improved = ng.note(events_of(asked, ("negotiation.improved", {"new_price": 36000.0, "old_price": 40000.0})))
    assert improved["outcome"] == "improved" and improved["saving"] == 4000.0 and "lowered it from 40,000.00 to 36,000.00 (saves 4,000.00, 10.0%)" in improved["text"]
    assert ng.note(events_of(asked, ("negotiation.no_improvement", {"why": "same_or_higher"})))["outcome"] == "kept"
    silent = ng.note(events_of(asked, ("negotiation.no_reply", {})))
    assert silent["outcome"] == "no_reply" and "did not answer in time" in silent["text"] and silent["saving"] is None


def test_a_new_round_forgets_the_old_negotiation():
    asked = (ng.ASKED, {"vendor": "Acme", "original_price": 40000.0})
    assert ng.note(events_of(asked, ("negotiation.improved", {"new_price": 1.0}), ("sourcing.restarted", {}))) is None


def test_an_approval_waiting_after_a_negotiation_shows_the_saving_in_the_review_and_the_email(w):
    case_id = quoted(w, prices=(("Acme", "900,000"), ("Globex", "950,000"), ("Initech", "970,000")))
    w.reply(case_id, "Acme", "Total Rs 850,000. Delivery 7 days. Terms: net 30")
    assert w.stage(case_id) == "awaiting_approval"
    approval_id = w.approvals[0].approval_id
    review = case_pipeline.approval_review(approval_id)
    assert review["negotiation"]["outcome"] == "improved" and review["negotiation"]["saving"] == 50000.0
    mail = next(m for m in w.sent if m[1].startswith("Approval needed"))
    assert "Negotiation: Acme was asked for a better price and lowered it from 900,000.00 to 850,000.00" in mail[2]


def test_an_approval_with_no_negotiation_has_no_note(w, monkeypatch):
    monkeypatch.setattr(settings, "NEGOTIATE_ENABLED", False)
    case_id = quoted(w, prices=(("Acme", "900,000"), ("Globex", "950,000"), ("Initech", "970,000")))
    assert case_pipeline.approval_review(w.approvals[0].approval_id)["negotiation"] is None
    assert "Negotiation:" not in next(m for m in w.sent if m[1].startswith("Approval needed"))[2] and case_id
