"""Automatic reorder: when an item reaches its minimum a reorder is raised by itself; an approver always approves it; never twice while one is
in progress; capped per pass; a cool-down; off until switched on."""

from datetime import datetime, timedelta

import pytest

from app.core import restock, tunables
from app.core.config import settings
from app.orchestrator import case_pipeline

from .fake_world import now, standard_world
from .test_end_to_end import source

NOW = datetime(2026, 10, 9, 12, 0)


def row(name, qty, lo=10, hi=40):
    return {"item_description": name, "quantity_available": qty, "min_level": lo, "target_level": hi}


def pick(stock, open_items=(), last=None, hours=24, limit=3):
    return restock.auto_candidates(stock, set(open_items), last or {}, NOW, hours, limit)


# ---- the rule -----------------------------------------------------------------------------------------------------------------------------

def test_an_item_at_or_below_its_minimum_is_reordered_up_to_its_target():
    got = pick([row("Lamp", 10), row("Chair", 3), row("Desk", 11)])
    assert [(c["item"], c["quantity"]) for c in got] == [("Chair", 37), ("Lamp", 30)]            # the shortest first; Desk (11 > 10) is fine


def test_items_without_both_levels_are_never_reordered_automatically():
    assert pick([{"item_description": "A", "quantity_available": 0, "min_level": None, "target_level": None},
                 {"item_description": "B", "quantity_available": 0, "min_level": 5, "target_level": None}]) == []


def test_an_item_with_a_reorder_in_progress_is_skipped_whatever_the_case():
    assert pick([row("Lamp", 2)], open_items={"lamp"}) == []


def test_the_cool_down_blocks_a_repeat_and_ends():
    assert pick([row("Lamp", 2)], last={"lamp": NOW - timedelta(hours=3)}) == []
    assert len(pick([row("Lamp", 2)], last={"lamp": NOW - timedelta(hours=25)})) == 1
    assert len(pick([row("Lamp", 2)], last={"lamp": NOW - timedelta(minutes=1)}, hours=0)) == 1       # 0 = no wait


def test_the_cap_limits_a_pass_and_a_cap_of_zero_raises_nothing():
    stock = [row(f"Item {n}", n) for n in range(6)]
    assert [c["item"] for c in pick(stock, limit=3)] == ["Item 0", "Item 1", "Item 2"] and pick(stock, limit=0) == []


# ---- through the pipeline -----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    monkeypatch.setattr(settings, "AUTO_REORDER_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_REORDER_MAX_PER_PASS", 3)
    monkeypatch.setattr(settings, "AUTO_REORDER_COOLDOWN_HOURS", 24.0)
    world = standard_world(monkeypatch)
    world.stock.clear()
    return world


def reorder_cases(w):
    return [cid for cid, events in w.events.items() if any(e.event_type == "restock.auto_triggered" for e in events)]


def test_it_is_off_until_switched_on(w, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_REORDER_ENABLED", False)
    w.add_stock("Lamp", 2, min_level=10, target_level=40)
    assert case_pipeline.auto_reorder_low_stock() == 0 and reorder_cases(w) == []


def test_a_low_item_gets_a_reorder_on_the_normal_road_and_stores_is_told(w):
    w.add_stock("Lamp", 4, min_level=10, target_level=40)
    assert case_pipeline.auto_reorder_low_stock() == 1
    case_id = reorder_cases(w)[0]
    types = w.event_types(case_id)
    assert "restock.requested" in types and "restock.auto_triggered" in types and w.requests[case_id].raw_request.startswith("Restock 36 x Lamp")
    assert w.cases[case_id].requester_id == "Procurement Agent"
    assert any("down to 4" in m[2] and "started automatically" in m[2] for m in w.emails_to("manager@x.co"))


def test_an_approver_always_approves_an_automatic_reorder_even_for_a_tiny_amount(w):
    w.add_stock("Lamp", 4, min_level=10, target_level=40)
    case_pipeline.auto_reorder_low_stock()
    case_id = reorder_cases(w)[0]
    w.add_vendor("Cheapo", 4.9)
    source(w, case_id, {"Acme": "Total Rs 500. Delivery 3 days. Terms: net 30", "Globex": "Total Rs 600. Delivery 3 days. Terms: net 30"})
    assert w.stage(case_id) == "awaiting_approval"                                     # Rs 500 would normally pass by itself


def test_it_never_raises_a_second_one_while_the_first_is_in_progress(w):
    w.add_stock("Lamp", 4, min_level=10, target_level=40)
    assert case_pipeline.auto_reorder_low_stock() == 1
    assert case_pipeline.auto_reorder_low_stock() == 0 and case_pipeline.auto_reorder_low_stock() == 0
    assert len(reorder_cases(w)) == 1


def test_a_manual_reorder_in_progress_also_blocks_it(w):
    w.add_stock("Lamp", 4, min_level=10, target_level=40)
    case_pipeline.restock_item("Lamp", 36, "stores")
    assert case_pipeline.auto_reorder_low_stock() == 0


def test_after_the_order_is_cancelled_it_waits_out_the_cool_down_then_tries_again(w):
    w.add_stock("Lamp", 4, min_level=10, target_level=40)
    case_pipeline.auto_reorder_low_stock()
    case_id = reorder_cases(w)[0]
    case_pipeline.cancel_case(case_id, "stores", "no longer wanted")
    assert case_pipeline.auto_reorder_low_stock() == 0                                 # still within 24 hours of the last automatic one
    for e in w.events[case_id]:
        if e.event_type == "restock.auto_triggered":
            e.created_at = now() - timedelta(hours=30)
    assert case_pipeline.auto_reorder_low_stock() == 1 and len(reorder_cases(w)) == 2


def test_many_low_items_are_raised_a_few_per_pass_the_shortest_first(w):
    for n in range(5):
        w.add_stock(f"Item {n}", n, min_level=10, target_level=40)
    assert case_pipeline.auto_reorder_low_stock() == 3
    assert {w.requests[c].raw_request.split(" x ")[1].split(" (")[0] for c in reorder_cases(w)} == {"Item 0", "Item 1", "Item 2"}
    assert case_pipeline.auto_reorder_low_stock() == 2 and case_pipeline.auto_reorder_low_stock() == 0


def test_one_failing_item_does_not_stop_the_others_and_is_retried_next_pass(w, monkeypatch):
    w.add_stock("Lamp", 1, min_level=10, target_level=40)
    w.add_stock("Chair", 2, min_level=10, target_level=40)
    real = case_pipeline.restock_item

    def flaky(item, *a, **k):
        if item == "Lamp":
            raise RuntimeError("db hiccup")
        return real(item, *a, **k)
    monkeypatch.setattr(case_pipeline, "restock_item", flaky)
    assert case_pipeline.auto_reorder_low_stock() == 1
    monkeypatch.setattr(case_pipeline, "restock_item", real)
    assert case_pipeline.auto_reorder_low_stock() == 1                                 # Lamp is tried again (no cool-down was started for it)
    assert len(reorder_cases(w)) == 2


def test_a_failing_stores_alert_never_undoes_the_reorder(w, monkeypatch):
    w.add_stock("Lamp", 4, min_level=10, target_level=40)
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    assert case_pipeline.auto_reorder_low_stock() == 1 and len(reorder_cases(w)) == 1


def test_the_worker_runs_the_check_every_pass_and_a_failure_does_not_stop_the_pass(w, monkeypatch):
    from app.orchestrator import worker
    calls = []
    monkeypatch.setattr(case_pipeline, "auto_reorder_low_stock", lambda: calls.append(1) or (_ for _ in ()).throw(RuntimeError("boom")))
    worker.run_once()
    assert calls == [1]


def test_the_settings_are_in_configure_with_safe_defaults():
    keys = {t.key: t for t in tunables.CATALOG}
    assert tunables.DEFAULTS["AUTO_REORDER_ENABLED"] is False and keys["AUTO_REORDER_ENABLED"].kind == "bool"
    assert tunables.validate({"AUTO_REORDER_MAX_PER_PASS": 5, "AUTO_REORDER_COOLDOWN_HOURS": 0}) == {"AUTO_REORDER_MAX_PER_PASS": 5, "AUTO_REORDER_COOLDOWN_HOURS": 0.0}
    with pytest.raises(tunables.InvalidSetting):
        tunables.validate({"AUTO_REORDER_MAX_PER_PASS": 0})
