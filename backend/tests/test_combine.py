"""Two people ask for the same item: the system suggests one combined order; a person decides."""

from datetime import datetime, timedelta

import pytest

from app.agents import approval_agent, operations_agent, purchase_agent, vendor_agent
from app.core import combine as cb
from app.core.config import settings
from app.core.exceptions import InvalidInput
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world

T0 = datetime(2026, 3, 2, 9)


# ---- the rules ----

def test_how_alike_two_descriptions_are():
    assert cb.similarity("Steel rack", "steel  RACK") == 1.0
    assert cb.similarity("Steel rack", "Steel storage rack") == pytest.approx(2 / 3)
    assert cb.similarity("Jetson 16GB", "Jetson 32GB") < cb.THRESHOLD            # the size is part of what is wanted
    assert cb.similarity("Laptop", "Monitor") == 0 and cb.similarity("", "x") == 0


def test_items_are_paired_once_each_and_summed():
    keep = [{"description": "Steel rack", "quantity": 8}, {"description": "Bracket", "quantity": 10}]
    fold = [{"description": "Steel storage rack", "quantity": 4}, {"description": "Lamp", "quantity": 2}]
    assert cb.overlap(keep, fold) == [{"item": "Steel rack", "primary_qty": 8, "secondary_qty": 4}]
    assert cb.merged_items(keep, fold) == [{"description": "Steel rack", "quantity": 12}, {"description": "Bracket", "quantity": 10}, {"description": "Lamp", "quantity": 2}]
    assert keep[0]["quantity"] == 8                                                # the inputs are untouched
    two = cb.merged_items([{"description": "Chair", "quantity": 1}], [{"description": "Chair", "quantity": 2}, {"description": "Chair", "quantity": 3}])
    assert sorted(i["quantity"] for i in two) == [3, 3] or sum(i["quantity"] for i in two) == 6      # each primary line is used once


def case(cid, stage="awaiting_quotes", status="open", hours_ago=1):
    return {"case_id": cid, "status": status, "stage": stage, "created_at": T0 - timedelta(hours=hours_ago)}


def test_only_recent_open_requests_before_an_order_are_candidates():
    me = case("me", hours_ago=0)
    others = [case("a"), case("b", stage="po_issued"), case("c", status="closed"), case("d", hours_ago=100), case("me"), case("e", stage="awaiting_approval")]
    assert [c["case_id"] for c in cb.candidates(me, others, 72, T0)] == ["a", "e"]


def test_the_older_request_carries_on():
    old, new = case("old", hours_ago=5), case("new", hours_ago=1)
    assert cb.primary_of(new, old) == (old, new) and cb.primary_of(old, new) == (old, new)


def ev(kind, case_id, other, minutes=0, **p):
    return {"event_type": kind, "case_id": case_id, "payload": {"primary_case_id": other, **p}, "created_at": T0 + timedelta(minutes=minutes)}


def test_a_suggestion_lasts_until_dismissed_merged_or_one_side_moves_on():
    cases = {"n": case("n"), "o": case("o")}
    suggest = ev(cb.SUGGESTED, "N", "O", matches=[{"item": "x"}])
    assert [(s["newer"], s["older"]) for s in cb.open_suggestions([suggest], cases)] == [("n", "o")]
    assert cb.open_suggestions([suggest, ev(cb.DISMISSED, "n", "o", 1)], cases) == []
    assert cb.open_suggestions([suggest, ev(cb.MERGED_INTO, "n", "o", 1)], cases) == []
    assert len(cb.open_suggestions([ev(cb.DISMISSED, "n", "o", 0), ev(cb.SUGGESTED, "n", "o", 1)], cases)) == 1       # suggested again after
    assert cb.open_suggestions([suggest], {"n": case("n"), "o": case("o", stage="po_issued")}) == []
    assert cb.open_suggestions([suggest], {"n": case("n", status="closed"), "o": case("o")}) == []
    assert cb.open_suggestions([suggest], {"n": case("n")}) == []


# ---- the flow ----

@pytest.fixture
def w(monkeypatch) -> World:
    world = standard_world(monkeypatch)
    world.add_stock("Widget", 0)
    world.teach("8 steel racks", [{"description": "Steel rack", "quantity": 8}])
    world.teach("4 steel storage racks", [{"description": "Steel storage rack", "quantity": 4}])
    world.teach("6 chairs", [{"description": "Chair", "quantity": 6}])
    return world


def two(w, first="8 steel racks", second="4 steel storage racks"):
    a = w.submit(first, requester="ann@x.co")
    w.cases[a].created_at -= timedelta(hours=2)                      # the first request is older
    b = w.submit(second, requester="bob@x.co")
    return a, b


def test_the_newer_request_suggests_combining_with_the_older(w):
    a, b = two(w)
    suggestions = case_pipeline.combine_suggestions()
    assert len(suggestions) == 1
    s = suggestions[0]
    assert (s["newer"], s["older"]) == (b, a) and s["matches"] == [{"item": "Steel rack", "primary_qty": 8, "secondary_qty": 4}]
    assert (s["newer_number"], s["older_number"]) == (w.cases[b].case_number, w.cases[a].case_number)
    assert [x["newer"] for x in case_pipeline.combine_suggestions(a)] == [b] and case_pipeline.combine_suggestions("nobody") == []
    assert combine_event_count(w, a) == 0                             # only the newer request records the suggestion


def combine_event_count(w, case_id):
    return w.event_types(case_id).count("combine.suggested")


def test_different_items_make_no_suggestion(w):
    w.submit("8 steel racks")
    w.submit("6 chairs")
    assert case_pipeline.combine_suggestions() == []


def test_it_can_be_switched_off(w, monkeypatch):
    monkeypatch.setattr(settings, "COMBINE_SUGGESTIONS", False)
    two(w)
    assert case_pipeline.combine_suggestions() == []


def test_dismissing_keeps_them_apart_and_does_not_come_back(w):
    a, b = two(w)
    case_pipeline.dismiss_combine(b, a, "vendor")
    assert case_pipeline.combine_suggestions() == []
    assert case_pipeline.suggest_combines(b) == 0                    # not suggested again


def test_combining_folds_the_newer_into_the_older_and_asks_the_suppliers_again(w):
    a, b = two(w)
    w.reply(a, "Acme", "Total Rs 42,000. Delivery 7 days. Terms: net 30")
    mark = len(w.sent)
    result = case_pipeline.combine_cases(b, a, "vendor")             # (the order of the two ids does not matter)
    assert result["primary_case_id"] == a and result["closed_case_id"] == b
    assert [(i["description"], i["quantity"]) for i in purchase_agent.get_purchase_request(a)["items"]] == [("Steel rack", 12)]
    assert w.stage(b) == "merged" and w.cases[b].status == "closed" and w.stage(a) == "awaiting_quotes"
    mails = w.sent[mark:]
    assert len([m for m in mails if "WITHDRAWN" in m[1]]) == 3 and len([m for m in mails if "fresh quotations" in m[2] and "Steel rack x 12" in m[2]]) == 3
    assert vendor_agent.get_quotes(a) == [] and len(vendor_agent.get_earlier_quotes(a)) == 1       # the price for 8 does not count for 12
    assert "case.merged_into" in w.event_types(b) and "request.changed" in w.event_types(a)
    assert case_pipeline.combine_suggestions() == []


def test_the_more_pressing_date_wins(w):
    from datetime import date
    a = case_pipeline.start_case("ann@x.co", "8 steel racks")
    w.cases[a].created_at -= timedelta(hours=2)
    b = case_pipeline.start_case("bob@x.co", "4 steel storage racks", needed_by=date.today() + timedelta(days=2))
    case_pipeline.combine_cases(a, b, "vendor")
    request = purchase_agent.get_purchase_request(a)
    assert request["needed_by"] == date.today() + timedelta(days=2) and request["urgent"] is True


def test_items_only_the_newer_wanted_are_added(w):
    w.teach("4 steel storage racks and 2 lamps", [{"description": "Steel storage rack", "quantity": 4}, {"description": "Lamp", "quantity": 2}])
    a, b = two(w, second="4 steel storage racks and 2 lamps")
    case_pipeline.combine_cases(a, b, "vendor")
    assert sorted((i["description"], i["quantity"]) for i in purchase_agent.get_purchase_request(a)["items"]) == [("Lamp", 2), ("Steel rack", 12)]


def test_a_waiting_approval_is_withdrawn_when_combined(w):
    a, b = two(w)
    for name, text in {"Acme": "Total Rs 90,000. Delivery 7 days. Terms: net 30", "Globex": "Total Rs 95,000. Delivery 7 days. Terms: net 30"}.items():
        w.reply(a, name, text)
    w.expire_quote_deadline(a)
    w.tick()
    assert w.stage(a) == "awaiting_approval"
    case_pipeline.combine_cases(a, b, "vendor")
    assert [x.status for x in w.approvals if x.case_id == a] == ["superseded"] and w.stage(a) == "awaiting_quotes"


def test_requests_that_cannot_be_combined_are_refused_without_changing_anything(w):
    a, b = two(w)
    with pytest.raises(InvalidInput, match="itself"):
        case_pipeline.combine_cases(a, a, "vendor")
    case_pipeline.cancel_case(b, "bob@x.co", None)
    with pytest.raises(InvalidInput, match="can no longer be combined"):
        case_pipeline.combine_cases(a, b, "vendor")
    assert purchase_agent.get_purchase_request(a)["items"][0]["quantity"] == 8 and w.stage(a) == "awaiting_quotes"


def test_a_request_with_an_order_cannot_be_combined(w):
    from .test_end_to_end import QUOTE_42K, QUOTE_45K, source
    a = w.submit("50 cameras")
    source(w, a, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    w.teach("10 cameras", [{"description": "CCTV camera", "quantity": 10}])
    b = w.submit("10 cameras")
    assert case_pipeline.combine_suggestions() == []                  # the first already has an order, so it is not offered
    with pytest.raises(InvalidInput):
        case_pipeline.combine_cases(a, b, "vendor")


def test_the_closed_request_reads_as_combined_to_its_requester(w):
    from app.core.agent_flow import build_flow
    a, b = two(w)
    case_pipeline.combine_cases(a, b, "vendor")
    flow = build_flow(operations_agent.get_case_status(b), operations_agent.get_case_events(b), "requester", datetime.utcnow())
    assert flow["outcome"] == "merged" and "combined with another request" in flow["headline"]
    assert "Combined" in {x["label"] for x in flow["agents"] if x["state"] == "stopped"}


def test_the_vendor_teams_my_work_lists_the_suggestion(w):
    from app.core.my_work import build_my_work
    a, b = two(w)
    cases = operations_agent.get_all_cases(None)
    work = build_my_work("vendor", lambda p: p == "vendors:write", approvals=[], cases=cases, deliveries=[], invoices=[], stock=[], now=datetime.utcnow(),
                         combine_suggestions=case_pipeline.combine_suggestions())
    item = next(i for i in work["queues"][0]["items"] if i["id"].startswith("combine:"))
    assert "Both ask for Steel rack (4 and 8)" in item["detail"] and item["link"] == f"/cases/{a}" and not item["urgent"]
