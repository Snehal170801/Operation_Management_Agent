"""Steps that take a moment say how far along they are ("reading quote 2 of 3"), so the live view is never a blank spinner."""

import pytest

from app.agents import operations_agent
from app.core import agent_flow

from .fake_world import standard_world


@pytest.fixture
def world(monkeypatch):
    w = standard_world(monkeypatch)
    w.teach("8 steel racks", [{"description": "Steel rack", "quantity": 8}])
    return w


def progress_of(w, case_id, step):
    """The progress lines recorded for one step, in order: (done, total, text)."""
    return [(e.payload["done"], e.payload["total"], e.payload["text"]) for e in w.events[case_id]
            if e.event_type == "step.progress" and e.payload["step"] == step]


def test_reading_each_quote_says_which_one_of_how_many(world):
    case = world.submit("8 steel racks")
    world.reply(case, "Acme", "Hello, 8 steel racks total Rs 20000, delivery 5 days, payment 30 days.")
    world.reply(case, "Globex", "Hello, 8 steel racks total Rs 21000, delivery 6 days, payment 30 days.")
    lines = progress_of(world, case, "read_quote")
    assert [t for _, _, t in lines] == [
        "Reading quote 1 of 3", "Understood the price and delivery time of quote 1",
        "Reading quote 2 of 3", "Understood the price and delivery time of quote 2",
    ]
    assert all(total == 3 for _, total, _ in lines)


def test_comparing_the_quotes_and_issuing_the_order_show_their_stages(world):
    case = world.submit("8 steel racks")
    for i, name in enumerate(("Acme", "Globex", "Initech")):
        world.reply(case, name, f"Hello, 8 steel racks total Rs {20000 + i * 1000}, delivery 5 days, payment 30 days.")
    assert [t for _, _, t in progress_of(world, case, "rank_quotes")] == [
        "Comparing 3 quotes side by side", "Ranking the suppliers and writing the reasons", "Recommendation ready"]
    assert [(d, t) for d, _, t in progress_of(world, case, "issue_po")] == [
        (1, "Creating the order"), (2, "Emailing the order to the supplier"), (3, "Order sent")]


def test_reminders_say_how_many_suppliers_have_been_reminded(world):
    case = world.submit("8 steel racks")
    for r in world.rfqs:
        r.sent_at = r.last_contacted_at = r.sent_at.replace(year=2000)   # a long time ago, so a reminder is due
    from app.orchestrator import case_pipeline
    case_pipeline.advance_sourcing(case)
    assert [t for _, _, t in progress_of(world, case, "remind_suppliers")] == [f"Reminded {n} of 3 suppliers" for n in (1, 2, 3)]


def test_progress_costs_nothing_outside_a_step(world):
    # Called directly (not inside a step), the agents do no extra reads and write no progress events.
    case = world.submit("8 steel racks")
    before = len(world.events[case])
    assert operations_agent.step_active() is False
    from app.agents import vendor_agent
    vendor_agent.submit_quote(case, world.vendor_id("Acme"), "Rs 20000, 5 days")
    assert not [e for e in world.events[case][before:] if e.event_type == "step.progress"]


def test_progress_text_never_carries_names_or_amounts(world):
    case = world.submit("8 steel racks")
    for i, name in enumerate(("Acme", "Globex", "Initech")):
        world.reply(case, name, f"Hello, 8 steel racks total Rs {20000 + i * 1000}, delivery 5 days, payment 30 days.")
    said = " ".join(e.payload["text"] or "" for e in world.events[case] if e.event_type == "step.progress")
    assert not any(word in said for word in ("Acme", "Globex", "Initech", "20000", "Rs"))
    _ = agent_flow  # the flow builder reads these same events
