"""The pause switch, the single-worker lock, the daily spend cap and duplicate-request protection."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents import approval_agent
from app.controllers import case_controller, system_controller
from app.core import access, automation, security
from app.core.approval_policy import human_review_reasons
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.models.auth_schemas import CurrentUser
from app.models.case_schemas import CreateCaseRequest
from app.orchestrator import case_pipeline, worker
from app.repositories import role_repository, user_repository

CASE = "3f2b8c1a-1111-4222-8333-444455556666"
client = TestClient(app)


# ---------- daily spend cap ----------

def test_spend_under_the_daily_cap_stays_automatic():
    assert human_review_reasons({"price": 40000.0}, 4.5, 3, spent_today=100000.0) == []


def test_crossing_the_daily_cap_needs_a_person():
    reasons = human_review_reasons({"price": 40000.0}, 4.5, 3, spent_today=180000.0)
    assert len(reasons) == 1 and "daily limit" in reasons[0] and "220,000.00" in reasons[0]


def test_the_cap_is_a_default_of_zero_spend_so_old_callers_are_unaffected():
    assert human_review_reasons({"price": 40000.0}, 4.5, 3) == []


def test_approval_agent_counts_todays_automatic_orders(monkeypatch):
    seen = {}
    monkeypatch.setattr(approval_agent.vendor_agent, "get_vendor_selection", lambda cid: {"vendor_id": "v1"})
    monkeypatch.setattr(approval_agent.vendor_agent, "get_quotes",
                        lambda cid: [{"vendor_id": "v1", "price": 40000.0}] * 3)
    monkeypatch.setattr(approval_agent.vendor_agent, "get_all_vendors",
                        lambda: [{"vendor_id": "v1", "reliability_score": 4.5}])
    monkeypatch.setattr(approval_agent.purchase_order_repository, "sum_auto_approved_since", lambda since: 190000.0)
    monkeypatch.setattr(approval_agent.approval_repository, "supersede_pending", lambda *a: None)
    monkeypatch.setattr(approval_agent.approval_repository, "insert_approval",
                        lambda aid, cid, t, status, reasons, decided_by=None: seen.update(status=status, reasons=reasons))
    monkeypatch.setattr(approval_agent, "get_approval", lambda aid: dict(seen))
    monkeypatch.setattr(approval_agent.operations_agent, "publish_event", lambda *a, **k: None)
    monkeypatch.setattr(approval_agent.operations_agent, "set_stage", lambda *a: None)
    approval_agent.review_vendor_selection(CASE)
    assert seen["status"] == "pending" and "daily limit" in seen["reasons"][0]


# ---------- pause switch ----------

def _pause(monkeypatch):
    monkeypatch.setattr(automation, "is_paused", lambda: True)


def test_paused_worker_does_nothing(monkeypatch):
    _pause(monkeypatch)
    touched = []
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda h: touched.append("mail"))
    monkeypatch.setattr(worker.case_pipeline, "track_deliveries", lambda: touched.append("delivery"))
    monkeypatch.setattr(worker.case_repository, "find_open_case_ids_by_stage", lambda s: touched.append("cases") or [])
    worker.run_once()
    assert touched == []


def test_a_worker_without_the_lease_stays_idle(monkeypatch):
    monkeypatch.setattr(automation, "acquire_worker_lease", lambda ttl: False)
    touched = []
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda h: touched.append("mail"))
    worker.run_once()
    assert touched == []


def test_the_worker_with_the_lease_runs_every_job(monkeypatch):
    ran = []
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda h: ran.append("mail"))
    monkeypatch.setattr(worker.case_repository, "find_open_case_ids_by_stage", lambda s: [])
    monkeypatch.setattr(worker.case_pipeline, "resume_held_cases", lambda: ran.append("resume"))
    monkeypatch.setattr(worker.case_pipeline, "remind_pending_approvals", lambda: ran.append("remind"))
    monkeypatch.setattr(worker.case_pipeline, "track_deliveries", lambda: ran.append("delivery"))
    worker.run_once()
    assert ran == ["mail", "resume", "remind", "delivery"]


def test_paused_system_still_takes_the_request_but_sends_no_supplier_emails(monkeypatch):
    _pause(monkeypatch)
    sent, events = [], []
    monkeypatch.setattr(case_pipeline.operations_agent, "create_case", lambda requester_id: CASE)
    monkeypatch.setattr(case_pipeline.purchase_agent, "create_purchase_request", lambda **kw: None)
    monkeypatch.setattr(case_pipeline.procurement_agent, "check_stock", lambda case_id: {"sufficient": False})
    monkeypatch.setattr(case_pipeline.vendor_agent, "send_rfqs", lambda cid, items, **kw: sent.append(cid) or ["Acme"])
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", lambda cid, t, **kw: events.append(t))
    assert case_pipeline.start_case("ravi@x.co", "50 cameras") == CASE
    assert sent == [] and events == ["automation.held"]


def test_paused_system_does_not_place_orders(monkeypatch):
    _pause(monkeypatch)
    issued, events = [], []
    monkeypatch.setattr(case_pipeline, "issue_purchase_order", lambda cid: issued.append(cid))
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", lambda cid, t, **kw: events.append(t))
    case_pipeline._issue_purchase_order_safely(CASE)
    assert issued == [] and events == ["automation.held"]


def test_resuming_catches_up_cases_that_were_held(monkeypatch):
    rfqs, orders = [], []
    idle = {"sourcing_needed": ["c1"], "approved": ["c2", "c3"]}
    monkeypatch.setattr(case_pipeline.operations_agent, "find_idle_cases", lambda stage, minutes: idle[stage])
    monkeypatch.setattr(case_pipeline.purchase_agent, "get_purchase_request",
                        lambda cid: {"items": [{"description": "Camera", "quantity": 50}]})
    monkeypatch.setattr(case_pipeline.vendor_agent, "send_rfqs", lambda cid, items, **kw: rfqs.append(cid) or ["Acme"])
    monkeypatch.setattr(case_pipeline, "_issue_purchase_order_safely", lambda cid: orders.append(cid))
    assert case_pipeline.resume_held_cases() == {"rfqs": 1, "purchase_orders": 2}
    assert rfqs == ["c1"] and orders == ["c2", "c3"]


def test_catch_up_alerts_a_human_when_no_supplier_can_be_reached(monkeypatch):
    alerts = []
    monkeypatch.setattr(case_pipeline.operations_agent, "find_idle_cases",
                        lambda stage, minutes: ["c1"] if stage == "sourcing_needed" else [])
    monkeypatch.setattr(case_pipeline.purchase_agent, "get_purchase_request", lambda cid: {"items": []})
    monkeypatch.setattr(case_pipeline.vendor_agent, "send_rfqs", lambda cid, items, **kw: [])
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled", lambda cid, reason, team=None: alerts.append(cid))
    case_pipeline.resume_held_cases()
    assert alerts == ["c1"]


# ---------- the switch itself is admin-controlled ----------

def test_only_admin_holds_the_pause_permission_by_default():
    assert "system:write" in ALL_PERMISSIONS
    for role in ("manager", "viewer", "user"):
        assert "system:write" not in DEFAULT_ROLE_PERMISSIONS[role]


@pytest.fixture
def people(monkeypatch):
    users = {
        "boss": SimpleNamespace(user_id="boss", username="boss@x.co", role="admin", is_active=True),
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
    }
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    audited = []
    monkeypatch.setattr(system_controller.audit, "record", lambda action, **kw: audited.append((action, kw)))
    state = {"paused": False}
    monkeypatch.setattr(system_controller.automation, "set_paused",
                        lambda paused, by: state.update(paused=paused, by=by) or
                        automation.AutomationState(paused, None, by))
    monkeypatch.setattr(system_controller.automation, "get_state",
                        lambda: automation.AutomationState(state["paused"], None, state.get("by")))
    access.invalidate()
    yield audited, state
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_an_admin_can_pause_and_it_is_audited_under_their_name(people):
    audited, state = people
    r = client.post("/system/automation", headers=as_("boss", "admin"), json={"paused": True})
    assert r.status_code == 200 and r.json()["paused"] is True and r.json()["updated_by"] == "boss@x.co"
    assert state["paused"] is True and audited[0][0] == "automation.pause"
    assert client.post("/system/automation", headers=as_("boss", "admin"), json={"paused": False}).json()["paused"] is False
    assert audited[1][0] == "automation.resume"


def test_a_manager_cannot_pause_or_even_see_the_switch(people):
    assert client.post("/system/automation", headers=as_("mgr", "manager"), json={"paused": True}).status_code == 403
    assert client.get("/system/automation", headers=as_("mgr", "manager")).status_code == 403


# ---------- duplicate requests ----------

def _user(role="user"):
    return CurrentUser(user_id="alice", username="alice@x.co", role=role)


@pytest.fixture
def case_world(monkeypatch):
    started = []
    monkeypatch.setattr(case_controller.case_pipeline, "start_case",
                        lambda requester_id, raw_request, **kw: started.append(raw_request) or "new-case")
    monkeypatch.setattr(case_controller.operations_agent, "count_recent_cases", lambda r, hours=24: 0)
    monkeypatch.setattr(case_controller.audit, "record", lambda *a, **k: None)
    monkeypatch.setattr(access, "has_permission", lambda role, perm: role == "admin")
    return started


def test_a_resubmitted_identical_request_returns_the_existing_case(case_world, monkeypatch):
    monkeypatch.setattr(case_controller.operations_agent, "find_recent_duplicate",
                        lambda requester, text, minutes: "existing-case")
    out = case_controller.create_case(CreateCaseRequest(raw_request="10 laptops"), _user())
    assert out.case_id == "existing-case" and case_world == []


def test_a_genuinely_new_request_is_processed(case_world):
    out = case_controller.create_case(CreateCaseRequest(raw_request="10 laptops"), _user())
    assert out.case_id == "new-case" and case_world == ["10 laptops"]


def test_surrounding_whitespace_does_not_defeat_the_duplicate_check(case_world, monkeypatch):
    seen = []
    monkeypatch.setattr(case_controller.operations_agent, "find_recent_duplicate",
                        lambda requester, text, minutes: seen.append(text) or None)
    case_controller.create_case(CreateCaseRequest(raw_request="  10 laptops \n"), _user())
    assert seen == ["10 laptops"] and case_world == ["10 laptops"]


def test_new_mail_is_read_straight_away_when_running(monkeypatch):
    from app.orchestrator import worker
    read = []
    monkeypatch.setattr(worker.automation, "is_paused", lambda: False)
    monkeypatch.setattr(worker.automation, "acquire_worker_lease", lambda ttl: True)
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda h: read.append("mail") or 1)
    assert worker.react_to_new_mail() == 1 and read == ["mail"]


def test_new_mail_is_left_alone_while_paused_or_without_the_lease(monkeypatch):
    from app.orchestrator import worker
    read = []
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda h: read.append("mail") or 1)
    monkeypatch.setattr(worker.automation, "is_paused", lambda: True)
    assert worker.react_to_new_mail() == 0
    monkeypatch.setattr(worker.automation, "is_paused", lambda: False)
    monkeypatch.setattr(worker.automation, "acquire_worker_lease", lambda ttl: False)
    assert worker.react_to_new_mail() == 0 and read == []


def test_the_two_mail_paths_never_read_at_once(monkeypatch):
    import threading
    import time
    from app.orchestrator import worker
    inside, overlap = [], []

    def slow_read(handler):
        inside.append(1)
        if len(inside) > 1:
            overlap.append(1)
        time.sleep(0.05)
        inside.pop()
        return 0
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", slow_read)
    threads = [threading.Thread(target=worker.read_mailbox) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert overlap == []


def test_the_watcher_reads_when_the_server_says_mail_arrived_and_survives_errors(monkeypatch):
    import asyncio
    from app.orchestrator import worker
    monkeypatch.setattr(worker.settings, "IMAP_HOST", "imap.example.com")
    calls = {"wait": 0, "react": 0}

    def wait(timeout):
        calls["wait"] += 1
        if calls["wait"] == 1:
            return True            # mail arrived
        if calls["wait"] == 2:
            raise RuntimeError("connection reset")   # must not kill the watcher
        raise asyncio.CancelledError   # test over
    monkeypatch.setattr(worker.imap_client, "wait_for_new_mail", wait)
    monkeypatch.setattr(worker, "react_to_new_mail", lambda: calls.__setitem__("react", calls["react"] + 1))

    real_sleep = asyncio.sleep

    async def quick(_):
        await real_sleep(0)
    monkeypatch.setattr(worker.asyncio, "sleep", quick)
    try:
        asyncio.run(worker.watch_mailbox_forever())
    except asyncio.CancelledError:
        pass
    assert calls["react"] == 1 and calls["wait"] == 3
