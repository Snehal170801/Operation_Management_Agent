from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import agent_flow_controller
from app.core import access, security
from app.core.agent_flow import BOARD_CASES_PER_AGENT, build_board, build_board_feed
from app.core.agent_steps import FLOW_AGENTS
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.repositories import role_repository, user_repository

from .test_agent_flow import NOW, Log, flow

client = TestClient(app)


def entry(case_id, stage, log=None, items="Camera (50)"):
    return ({"case_id": case_id, "items_summary": items, "requester_id": "ravi"}, flow(stage, "open", log))


def col(board, key):
    return next(a for a in board["agents"] if a["key"] == key)


def test_every_agent_has_a_column_even_with_no_cases():
    board = build_board([], NOW)
    assert [a["name"] for a in board["agents"]] == list(FLOW_AGENTS)
    assert board["open_cases"] == 0 and all(a["cases"] == [] and a["working"] == 0 for a in board["agents"])


def test_cases_are_counted_under_the_agent_they_are_with():
    board = build_board([entry("a", "awaiting_quotes"), entry("b", "awaiting_quotes"), entry("c", "po_issued")], NOW)
    assert col(board, "vendor")["waiting"] == 2 and col(board, "delivery")["waiting"] == 1
    assert board["open_cases"] == 3 and board["working_now"] == 0 and board["needs_person"] == 0


def test_a_running_step_counts_as_working_and_is_listed_first():
    busy = Log().start("rank_quotes")
    board = build_board([entry("w", "awaiting_quotes"), entry("x", "awaiting_quotes", busy)], NOW)
    vendor = col(board, "vendor")
    assert vendor["working"] == 1 and vendor["waiting"] == 1 and board["working_now"] == 1
    assert [c["case_id"] for c in vendor["cases"]] == ["x", "w"]


def test_cases_needing_a_person_come_first_and_are_counted():
    board = build_board([entry("a", "awaiting_quotes"), entry("b", "sourcing_stalled")], NOW)
    vendor = col(board, "vendor")
    assert vendor["needs_person"] == 1 and vendor["cases"][0]["case_id"] == "b" and board["needs_person"] == 1


def test_done_and_pending_agents_list_no_cases():
    board = build_board([entry("a", "po_issued")], NOW)
    assert col(board, "purchase")["cases"] == [] and col(board, "invoice")["cases"] == []


def test_a_long_column_is_cut_and_says_how_many_more():
    many = [entry(f"c{i}", "awaiting_quotes") for i in range(BOARD_CASES_PER_AGENT + 5)]
    vendor = col(build_board(many, NOW), "vendor")
    assert len(vendor["cases"]) == BOARD_CASES_PER_AGENT and vendor["more"] == 5
    # the counts cover every case, not just the ones listed
    assert vendor["waiting"] == BOARD_CASES_PER_AGENT + 5


@pytest.fixture
def people(monkeypatch):
    users = {"alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
             "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True)}
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    ops = agent_flow_controller.operations_agent
    monkeypatch.setattr(ops, "get_all_cases", lambda requester_id=None: [
        {"case_id": "c1", "requester_id": "ravi", "stage": "awaiting_quotes", "status": "open", "items_summary": "Camera (50)", "updated_at": NOW},
        {"case_id": "c2", "requester_id": "ravi", "stage": "completed", "status": "closed", "items_summary": "Laptop", "updated_at": NOW}])
    monkeypatch.setattr(ops, "get_case_events", lambda cid: [])
    monkeypatch.setattr(agent_flow_controller.dashboard_repository, "recent_agent_events", lambda limit=80: [
        SimpleNamespace(event_id=5, case_id="c1", case_number="REQ-2026-0001", event_type="step.started", agent_name="Vendor Agent",
                        payload='{"step": "rank_quotes", "run": "a"}', created_at=NOW)])
    access.invalidate()
    yield
    access.invalidate()


def as_(uid, role):
    t, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {t}"}


def test_a_requester_cannot_see_the_board(people):
    assert client.get("/agent-flow/board", headers=as_("alice", "user")).status_code == 403


def test_staff_get_only_open_cases_on_the_board(people):
    body = client.get("/agent-flow/board", headers=as_("mgr", "manager")).json()
    assert body["open_cases"] == 1
    assert [c["case_id"] for c in next(a for a in body["agents"] if a["key"] == "vendor")["cases"]] == ["c1"]


def test_the_board_carries_what_each_working_agent_is_doing_right_now():
    busy = Log().start("rank_quotes")
    vendor = col(build_board([entry("x", "awaiting_quotes", busy)], NOW), "vendor")
    assert vendor["now_doing"] == "Comparing the quotes"
    assert col(build_board([entry("w", "awaiting_quotes")], NOW), "vendor")["now_doing"] is None


def feed_event(i, event_type, payload=None, case="c1"):
    return {"event_id": i, "event_type": event_type, "created_at": NOW, "case_id": case, "case_number": f"REQ-2026-000{i}", "payload": payload}


def test_the_cross_case_feed_is_newest_first_with_case_numbers_and_skips_noise():
    events = [feed_event(1, "step.started", {"step": "check_stock", "run": "a"}),
              feed_event(2, "step.progress", {"step": "check_stock", "run": "a", "done": 1, "total": 2}),
              feed_event(3, "quote.submitted", {"price": 42000}),
              feed_event(4, "po.issued", {"po_number": "PO-1"}, case="c2")]
    feed = build_board_feed(events)
    assert [(f["case_number"], f["agent"], f["text"]) for f in feed] == [
        ("REQ-2026-0004", "PO", "Order sent to the supplier"), ("REQ-2026-0001", "Procurement", "Checking stock")]


def test_the_cross_case_feed_is_capped():
    events = [feed_event(i, "step.started", {"step": "read_quote", "run": str(i)}) for i in range(1, 40)]
    assert len(build_board_feed(events, limit=14)) == 14


def test_the_board_over_http_includes_the_feed(people):
    body = client.get("/agent-flow/board", headers=as_("mgr", "manager")).json()
    assert body["feed"][0]["text"] == "Comparing the quotes" and body["feed"][0]["case_number"] == "REQ-2026-0001"
