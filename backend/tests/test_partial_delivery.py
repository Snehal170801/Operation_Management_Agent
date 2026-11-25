"""Part deliveries: only some of the order arrives. Chase for the rest, bill for what came, close only when it is all settled."""

from datetime import date, timedelta

import pytest

from app.agents import delivery_agent, operations_agent
from app.core import partial_delivery as pd
from app.core.exceptions import InvalidInput
from app.core.invoice_policy import evaluate_invoice
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

ITEMS = [{"description": "Steel rack", "quantity": 8}, {"description": "Bracket", "quantity": 10}]


# ---- the pure rules ----

def test_progress_and_outstanding():
    batches = [{"items": {"steel rack": 3, "Bracket": 10}}, {"items": {"Steel Rack": 2}}]
    lines = pd.progress(ITEMS, batches)
    assert [(l["received"], l["outstanding"]) for l in lines] == [(5, 3), (10, 0)]
    assert pd.units(lines) == (15, 18) and pd.is_partial(lines) and not pd.is_complete(lines)
    assert pd.summary(lines) == "15 of 18 received" and pd.outstanding_text(lines) == "Steel rack × 3"
    assert pd.is_complete(pd.progress(ITEMS, batches + [{"items": {"steel rack": 3}}]))
    assert not pd.is_partial(pd.progress(ITEMS, []))


def test_a_receipt_defaults_to_everything_owed_and_rejects_nonsense():
    assert pd.normalise_receipt(ITEMS, [], None) == {"Steel rack": 8, "Bracket": 10}
    assert pd.normalise_receipt(ITEMS, [], {"steel  RACK": 3, "bracket": 0}) == {"Steel rack": 3}
    for bad in ({"Chair": 1}, {"Steel rack": -1}, {"Steel rack": 9}, {"Steel rack": 0}, {}, {"Steel rack": True}):
        with pytest.raises(pd.BadReceipt):
            pd.normalise_receipt(ITEMS, [], bad)
    with pytest.raises(pd.BadReceipt):
        pd.normalise_receipt(ITEMS, [{"items": {"Steel rack": 8, "Bracket": 10}}], None)       # nothing left to receive


def test_garbled_stored_batches_are_ignored_not_fatal():
    assert pd.parse_batches("not json") == [] and pd.parse_batches(None) == [] and pd.parse_batches('{"a": 1}') == []


# ---- invoices for part deliveries ----

PO = {"po_number": "PO-1", "total_amount": 1000.0, "items": [{"description": "x", "quantity": 10}]}


def inv(total, qty=None):
    return {"invoice_number": "I", "total_amount": total, "po_number": "PO-1", "items": [{"description": "x", "quantity": qty}] if qty else []}


def judge(invoice, **partial):
    base = {"received_units": 4, "ordered_units": 10, "invoiced_so_far": 0.0, "closed_short": False}
    return evaluate_invoice(PO, invoice, False, False, 1.0, {**base, **partial})


def test_billing_for_what_arrived_clears_now_and_billing_the_whole_balance_waits():
    assert judge(inv(400.0, 4)) == ("matched", [])
    assert judge(inv(1000.0, 10)) == ("on_hold", ["Waiting for the goods to be confirmed as received."])
    status, issues = judge(inv(700.0))
    assert status == "mismatch" and "400.00 for what has arrived so far, or 1,000.00 for the whole balance" in issues[0]


def test_a_second_invoice_is_for_the_balance():
    assert evaluate_invoice(PO, inv(600.0), True, False, 1.0, {"received_units": 10, "ordered_units": 10, "invoiced_so_far": 400.0, "closed_short": False}) == ("matched", [])
    assert evaluate_invoice(PO, inv(1000.0), True, False, 1.0, {"received_units": 10, "ordered_units": 10, "invoiced_so_far": 400.0, "closed_short": False})[0] == "mismatch"


def test_after_closing_short_only_what_arrived_is_owed():
    assert judge(inv(400.0), closed_short=True) == ("matched", [])
    assert judge(inv(1000.0), closed_short=True)[0] == "mismatch"


def test_orders_not_delivered_in_parts_are_judged_exactly_as_before():
    assert evaluate_invoice(PO, inv(1000.0), True, False, 1.0) == ("matched", [])
    assert evaluate_invoice(PO, inv(400.0), True, False, 1.0)[0] == "mismatch"


# ---- the whole flow ----

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def ordered(w) -> str:
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def reply(w, case_id, text):
    return w.reply(case_id, w.pos[case_id].vendor_name, text, subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")


def test_part_delivery_keeps_the_order_open_and_records_what_came(w):
    case_id = ordered(w)
    result = case_pipeline.confirm_delivery(case_id, "recv", "first lorry", {"CCTV camera": 30})
    assert result["delivery_status"] == "pending" and result["partial"] and (result["received_units"], result["ordered_units"]) == (30, 50)
    assert w.stage(case_id) == "po_issued" and w.cases[case_id].status == "open"
    ev = next(e for e in operations_agent.get_case_events(case_id) if e["event_type"] == "delivery.partial")
    assert ev["payload"]["outstanding"] == "CCTV camera × 20" and ev["payload"]["received_units"] == 30
    assert "delivery.received" not in w.event_types(case_id)


def test_the_rest_arriving_completes_it_and_a_stranger_cannot_overreceive(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    with pytest.raises(InvalidInput, match="more than is still owed"):
        case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 21})
    done = case_pipeline.confirm_delivery(case_id, "recv", None)                                  # no items: everything still owed
    assert done["delivery_status"] == "delivered" and not done["partial"]
    assert w.stage(case_id) == "delivered"
    assert next(e for e in operations_agent.get_case_events(case_id) if e["event_type"] == "delivery.received")["payload"]["in_parts"] == 2


def test_the_supplier_is_chased_only_for_the_rest(w):
    case_id = ordered(w)
    w.pos[case_id].expected_delivery_date = date.today() - timedelta(days=2)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    mark = len(w.sent)
    case_pipeline.track_deliveries()
    chase = w.sent[mark:]
    assert len(chase) == 1 and "30 of 50" in chase[0][2] and "CCTV camera × 20" in chase[0][2]


def test_billing_for_the_part_that_came_then_the_balance_then_the_case_closes(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    assert reply(w, case_id, "Invoice INV-8 for PO-1001. Total Rs 25,200. 30 x CCTV camera.") == "invoiced"
    assert [i.status for i in w.invoices] == ["matched"] and w.cases[case_id].status == "open"       # cleared, but the order is not finished
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert w.cases[case_id].status == "open"                                                          # delivered, but only 60% billed
    assert reply(w, case_id, "Invoice INV-9 for PO-1001. Total Rs 16,800. 20 x CCTV camera.") == "invoiced"
    assert [i.status for i in w.invoices] == ["matched", "matched"]
    assert w.stage(case_id) == "completed" and w.cases[case_id].status == "closed"


def test_the_whole_invoice_sent_early_waits_for_the_rest_of_the_goods(w):
    case_id = ordered(w)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    reply(w, case_id, "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    assert [i.status for i in w.invoices] == ["on_hold"]
    case_pipeline.confirm_delivery(case_id, "recv", None)
    assert [i.status for i in w.invoices] == ["matched"] and w.cases[case_id].status == "closed"


def test_closing_short_accepts_what_came_and_bills_for_it(w):
    case_id = ordered(w)
    with pytest.raises(InvalidInput, match="Nothing has arrived"):
        case_pipeline.short_close_delivery(case_id, "recv", None)
    case_pipeline.confirm_delivery(case_id, "recv", None, {"CCTV camera": 30})
    result = case_pipeline.short_close_delivery(case_id, "recv", "supplier discontinued the rest")
    assert result["delivery_status"] == "delivered" and w.pos[case_id].short_closed_at is not None
    assert w.stage(case_id) == "delivered" and w.cases[case_id].status == "open"                      # still needs its invoice
    assert "delivery.short_closed" in w.event_types(case_id)
    reply(w, case_id, "Invoice INV-8 for PO-1001. Total Rs 25,200. 30 x CCTV camera.")
    assert w.cases[case_id].status == "closed"
    # no more chasing a finished order
    w.pos[case_id].expected_delivery_date = date.today() - timedelta(days=5)
    assert case_pipeline.track_deliveries() == {"chased": 0, "escalated": 0}


def test_an_ordinary_full_delivery_is_unchanged(w):
    case_id = ordered(w)
    result = case_pipeline.confirm_delivery(case_id, "recv", None)
    assert result["delivery_status"] == "delivered" and w.stage(case_id) == "delivered"
    assert "delivery.partial" not in w.event_types(case_id)
    assert delivery_agent.get_delivery(case_id)["batches"][0]["items"] == {"CCTV camera": 50}
