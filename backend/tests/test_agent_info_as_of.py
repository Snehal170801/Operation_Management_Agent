"""Replay: click an agent and see it as it was at that moment, never the future."""

from datetime import datetime, timedelta

from app.core.agent_info import as_of, build_agent_info

T0 = datetime(2026, 10, 2, 9, 0)


def t(hours):
    return T0 + timedelta(hours=hours)


def ev(i, kind, hours, agent=None, payload=None):
    return {"event_id": i, "event_type": kind, "agent_name": agent, "payload": payload or {}, "created_at": t(hours)}


def case():
    quote = lambda vid, name, price, hours: {"quote_id": vid, "vendor_id": vid, "vendor_name": name, "price": price, "lead_time_days": 5,
                                             "terms": "30 days", "raw_quote_text": f"{name} says Rs {price}", "created_at": t(hours)}
    return {
        "case": {"requester_id": "ann", "stage": "completed", "status": "closed", "created_at": t(0)},
        "events": [
            ev(1, "case.created", 0), ev(2, "rfq.sent", 1),
            ev(3, "rfq.reminded", 6, payload={"vendors": ["Acme", "Globex"]}),
            ev(4, "vendor.selected", 8, payload={"vendor_id": "a", "rationale": "Acme first", "ranking": [{"vendor_id": "a", "rank": 1, "reason": "x"}]}),
            ev(5, "vendor.selected", 20, payload={"vendor_id": "g", "rationale": "Chosen by boss instead of Acme.", "chosen_by": "boss"}),
            ev(6, "approval.approved", 21), ev(7, "po.issued", 22), ev(8, "delivery.chased", 50), ev(9, "delivery.chased", 75),
            ev(10, "delivery.received", 100), ev(11, "invoice.mismatch", 101, payload={"invoice_id": "i1"}), ev(12, "invoice.rejected", 110, payload={"invoice_id": "i1"}),
        ],
        "rfqs": [
            {"vendor_id": "a", "vendor_name": "Acme", "status": "replied", "sent_at": t(1), "replied_at": t(7), "reminder_count": 1, "deadline_at": t(49)},
            {"vendor_id": "g", "vendor_name": "Globex", "status": "replied", "sent_at": t(1), "replied_at": t(19), "reminder_count": 1, "deadline_at": t(49)},
        ],
        "quotes": [quote("a", "Acme", 20000, 7), quote("g", "Globex", 21000, 19)],
        "vendors": {"a": {"name": "Acme", "reliability_score": 4.5}, "g": {"name": "Globex", "reliability_score": 4.2}},
        "selection": {"vendor_id": "g", "vendor_name": "Globex", "rationale": "Chosen by boss instead of Acme.", "created_at": t(20)},
        "approvals": [{"approval_id": "p1", "status": "approved", "reasons": ["big"], "decided_by": "boss", "decision_note": "ok", "created_at": t(9), "decided_at": t(21)}],
        "po": {"po_number": "PO-1", "vendor_id": "g", "vendor_name": "Globex", "total_amount": 21000.0, "items": [], "status": "sent", "created_at": t(21.5), "sent_at": t(22)},
        "delivery": {"po_number": "PO-1", "delivery_status": "delivered", "delivered_at": t(100), "received_by": "recv", "delivery_note": "all good",
                     "chase_count": 2, "last_chased_at": t(75), "escalated_at": t(90), "expected_delivery_date": None},
        "invoices": [{"invoice_id": "i1", "invoice_number": "INV-1", "total_amount": 21000.0, "status": "rejected", "issues": ["wrong total"],
                      "decided_by": "acc", "decision_note": "no", "created_at": t(101), "decided_at": t(110), "vendor_name": "Globex", "vendor_id": "g", "po_number": "PO-1", "source": "email",
                      "raw_text": "", "extracted": {}}],
    }


def test_early_on_only_the_early_things_exist():
    d = as_of(case(), t(5))
    assert [q["vendor_name"] for q in d["quotes"]] == []
    assert [r["reminder_count"] for r in d["rfqs"]] == [0, 0] and [r["status"] for r in d["rfqs"]] == ["sent", "sent"]
    assert d["selection"] is None and d["approvals"] == [] and d["po"] is None and d["delivery"] is None and d["invoices"] == []
    assert [e["event_type"] for e in d["events"]] == ["case.created", "rfq.sent"]


def test_suppliers_replies_and_reminders_appear_as_they_happened():
    d = as_of(case(), t(10))
    assert [q["vendor_name"] for q in d["quotes"]] == ["Acme"]
    assert {r["vendor_name"]: (r["status"], r["reminder_count"]) for r in d["rfqs"]} == {"Acme": ("replied", 1), "Globex": ("sent", 1)}
    assert d["selection"]["vendor_name"] == "Acme" and d["selection"]["rationale"] == "Acme first"   # the first pick, before the boss overrode it
    assert d["approvals"][0]["status"] == "pending" and d["approvals"][0]["decided_by"] is None       # raised at 9h, decided at 21h


def test_the_override_shows_only_after_it_was_made():
    assert as_of(case(), t(19))["selection"]["vendor_name"] == "Acme"
    later = as_of(case(), t(23))
    assert later["selection"]["vendor_name"] == "Globex" and later["approvals"][0]["status"] == "approved"
    assert later["po"]["status"] == "sent"


def test_the_order_is_issued_before_it_is_emailed():
    d = as_of(case(), t(21.7))
    assert d["po"]["status"] == "issued" and d["po"]["sent_at"] is None


def test_delivery_chasing_builds_up_and_goods_are_not_received_until_they_were():
    mid = as_of(case(), t(80))["delivery"]
    assert (mid["chase_count"], mid["delivery_status"], mid["received_by"], mid["escalated_at"]) == (2, "pending", None, None)
    assert as_of(case(), t(60))["delivery"]["chase_count"] == 1
    done = as_of(case(), t(101))["delivery"]
    assert done["delivery_status"] == "delivered" and done["received_by"] == "recv" and done["escalated_at"] is not None


def test_an_invoice_is_shown_as_it_was_before_it_was_rejected():
    waiting = as_of(case(), t(105))["invoices"][0]
    assert waiting["status"] == "mismatch" and waiting["decided_by"] is None
    final = as_of(case(), t(120))["invoices"][0]
    assert final["status"] == "rejected" and final["decided_by"] == "acc"


def test_the_real_account_is_not_changed_and_the_end_matches_the_live_view():
    live = case()
    snapshot = as_of(live, t(10))
    assert len(live["quotes"]) == 2 and live["approvals"][0]["status"] == "approved"      # input untouched
    end = as_of(case(), t(500))
    for key in ("vendor", "approval", "po", "delivery", "invoice"):
        assert build_agent_info(key, end, True)["sections"] == build_agent_info(key, case(), True)["sections"], key
    assert snapshot is not live


def test_what_the_vendor_agent_shows_at_that_moment_has_only_that_moments_replies():
    info = build_agent_info("vendor", as_of(case(), t(10)), True)
    replies = next(s for s in info["sections"] if s["title"] == "What each supplier replied")
    assert [row[0] for row in replies["rows"]] == ["Acme"]
