"""The live "what is each agent doing right now" signals: step.started / progress / finished / failed."""

import re
from pathlib import Path

import pytest

from app.agents import operations_agent
from app.core.agent_steps import FLOW_AGENTS, STEP_EVENTS, STEPS
from app.orchestrator import case_pipeline
from app.repositories import case_repository

from .fake_world import World, standard_world

CASE = "3f2b8c1a-1111-4222-8333-444455556666"


@pytest.fixture
def recorded(monkeypatch):
    rows = []
    monkeypatch.setattr(case_repository, "insert_event",
                        lambda case_id, event_type, agent_name=None, payload=None: rows.append((event_type, agent_name, payload)))
    return rows


# ---------- the helper ----------

def test_a_successful_step_is_started_then_finished_with_the_same_run_id(recorded):
    with operations_agent.working(CASE, "check_stock"):
        pass
    assert [r[0] for r in recorded] == ["step.started", "step.finished"]
    started, finished = recorded[0][2], recorded[1][2]
    assert started["run"] == finished["run"] and started["step"] == "check_stock"
    assert started["label"] == "Checking stock" and recorded[0][1] == "Procurement Agent"
    assert finished["seconds"] >= 0


def test_a_failing_step_is_marked_failed_and_the_error_still_reaches_the_caller(recorded):
    with pytest.raises(ValueError, match="boom"):
        with operations_agent.working(CASE, "read_request"):
            raise ValueError("boom")
    assert [r[0] for r in recorded] == ["step.started", "step.failed"]
    assert recorded[1][2]["error"] == "boom" and "seconds" not in recorded[1][2]


def test_a_long_error_message_is_cut_down(recorded):
    with pytest.raises(RuntimeError):
        with operations_agent.working(CASE, "read_request"):
            raise RuntimeError("x" * 5000)
    assert len(recorded[1][2]["error"]) == 200


def test_progress_reported_from_inside_the_step_is_recorded_against_it(recorded):
    with operations_agent.working(CASE, "request_quotes"):
        operations_agent.report_progress(1, 3, "Asked 1 of 3 suppliers")
        operations_agent.report_progress(3, 3)
    types = [r[0] for r in recorded]
    assert types == ["step.started", "step.progress", "step.progress", "step.finished"]
    first = recorded[1][2]
    assert (first["done"], first["total"], first["text"]) == (1, 3, "Asked 1 of 3 suppliers")
    assert first["run"] == recorded[0][2]["run"]


def test_progress_outside_any_step_does_nothing(recorded):
    operations_agent.report_progress(1, 2, "no step is active")
    assert recorded == []


def test_progress_goes_to_the_innermost_step_then_back_to_the_outer_one(recorded):
    with operations_agent.working(CASE, "rank_quotes"):
        with operations_agent.working(CASE, "issue_po"):
            operations_agent.report_progress(1, 1, "inner")
        operations_agent.report_progress(1, 2, "outer")
    progress = [r for r in recorded if r[0] == "step.progress"]
    assert [(p[2]["step"], p[2]["text"]) for p in progress] == [("issue_po", "inner"), ("rank_quotes", "outer")]
    operations_agent.report_progress(9, 9, "after")
    assert len([r for r in recorded if r[0] == "step.progress"]) == 2     # nothing active any more


def test_two_runs_of_the_same_step_get_different_run_ids(recorded):
    for _ in range(2):
        with operations_agent.working(CASE, "read_quote"):
            pass
    assert recorded[0][2]["run"] != recorded[2][2]["run"]


def test_a_signal_that_cannot_be_saved_never_breaks_the_real_work(monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("database is down")

    monkeypatch.setattr(case_repository, "insert_event", broken)
    result = []
    with operations_agent.working(CASE, "check_stock"):
        operations_agent.report_progress(1, 1, "x")
        result.append("the work still ran")
    assert result == ["the work still ran"]


def test_detail_is_kept_for_staff_in_the_started_event(recorded):
    with operations_agent.working(CASE, "check_stock", detail="3 lines"):
        pass
    assert recorded[0][2]["detail"] == "3 lines"


# ---------- the catalogue ----------

def test_every_step_belongs_to_a_known_agent_and_has_a_friendly_label():
    for key, step in STEPS.items():
        assert step.key == key and step.label and step.label[0].isupper()
        assert step.agent in FLOW_AGENTS, f"{key} is attributed to {step.agent}, which is not drawn on the flow"


def test_labels_never_contain_anything_a_requester_should_not_see():
    for step in STEPS.values():
        # no digits (amounts, counts) and no currency wording
        assert not re.search(r"\d|₹|\brs\b|\binr\b|\bprice of\b", step.label.lower()), step.label


def test_the_pipeline_only_uses_steps_that_exist():
    source = Path(case_pipeline.__file__).read_text(encoding="utf-8")
    used = set(re.findall(r'working\([^,]+,\s*"([a-z_]+)"', source))
    assert used and used <= set(STEPS), used - set(STEPS)
    # ...and every defined step is actually used somewhere (no dead entries to confuse the page)
    assert set(STEPS) <= used, set(STEPS) - used


def test_flow_agents_are_unique_and_in_order():
    assert len(FLOW_AGENTS) == len(set(FLOW_AGENTS)) and FLOW_AGENTS[0] == "Purchase Agent" and FLOW_AGENTS[-1] == "Invoice Agent"
    assert STEP_EVENTS == {"step.started", "step.progress", "step.finished", "step.failed"}


# ---------- through the real flow ----------

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def steps_of(w: World, case_id: str):
    return [(e.event_type.split(".")[1], e.payload["step"]) for e in w.events[case_id] if e.event_type in STEP_EVENTS]


def test_a_routine_purchase_shows_every_agent_working_in_order(w):
    case_id = w.submit("50 cameras")
    for vendor, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30",
                         "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, vendor, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    w.reply(case_id, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.",
            subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")

    finished_order = [step for kind, step in steps_of(w, case_id) if kind == "finished"]
    assert finished_order == ["read_request", "check_stock", "request_quotes", "read_quote", "read_quote",
                              "rank_quotes", "review_approval", "issue_po", "read_invoice", "match_invoice"]


def test_every_step_that_starts_also_ends(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "Total Rs 42,000. Delivery 7 days. Terms: net 30")
    w.reply(case_id, "Globex", "Total Rs 45,000. Delivery 5 days. Terms: net 30")
    w.expire_quote_deadline(case_id)
    w.tick()
    started = {e.payload["run"] for e in w.events[case_id] if e.event_type == "step.started"}
    ended = {e.payload["run"] for e in w.events[case_id] if e.event_type in ("step.finished", "step.failed")}
    assert started and started == ended          # nothing left looking "busy" forever


def test_the_stock_check_and_supplier_emails_report_how_far_along_they_are(w):
    case_id = w.submit("50 cameras")
    progress = [(e.payload["step"], e.payload["done"], e.payload["total"], e.payload["text"])
               for e in w.events[case_id] if e.event_type == "step.progress"]
    assert ("check_stock", 1, 1, "CCTV camera") in progress
    assert [p[1:] for p in progress if p[0] == "request_quotes"] == [
        (1, 3, "Asked 1 of 3 suppliers"), (2, 3, "Asked 2 of 3 suppliers"), (3, 3, "Asked 3 of 3 suppliers")]


def test_enough_stock_means_only_the_first_two_agents_ever_work(w):
    case_id = w.submit("10 laptops")
    assert {step for _, step in steps_of(w, case_id)} == {"read_request", "check_stock"}


def test_an_agent_that_fails_is_shown_as_failed_not_stuck_busy(w):
    with pytest.raises(KeyError):                 # the fake AI has no answer for this request
        w.submit("a request the AI cannot read")
    case_id = next(iter(w.cases))
    assert steps_of(w, case_id) == [("started", "read_request"), ("failed", "read_request")]


def test_a_chased_supplier_shows_the_delivery_agent_working(w):
    from datetime import date, timedelta
    case_id = w.submit("50 cameras")
    for vendor, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30",
                         "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, vendor, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    w.pos[case_id].expected_delivery_date = date.today() - timedelta(days=2)
    w.tick()
    assert ("finished", "chase_delivery") in steps_of(w, case_id)
