from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents import purchase_agent
from app.controllers import agent_flow_controller
from app.core import access, security
from app.core.agent_flow import build_flow, headline_for
from app.core.agent_steps import FLOW_AGENTS
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.orchestrator import case_pipeline
from app.repositories import role_repository, user_repository

from .fake_world import World, now as utc_now, standard_world

NOW = datetime(2026, 10, 10, 12, 0)
client = TestClient(app)

PENDING, WORKING, WAITING, NEEDS, DONE, SKIPPED, STOPPED, FAILED = (
    "pending", "working", "waiting", "needs_person", "done", "skipped", "stopped", "failed")


# ---------- building events by hand ----------

class Log:
    def __init__(self):
        self.events, self._n = [], 0

    def add(self, event_type, payload=None, ago=0, agent=None):
        self._n += 1
        self.events.append({"event_id": self._n, "event_type": event_type, "agent_name": agent,
                            "payload": payload, "created_at": NOW - timedelta(seconds=ago)})
        return self

    def start(self, step, run="r1", ago=5, detail=None):
        return self.add("step.started", {"step": step, "run": run, "label": step, "detail": detail}, ago)

    def progress(self, step, done, total, text=None, run="r1", ago=4):
        return self.add("step.progress", {"step": step, "run": run, "done": done, "total": total, "text": text}, ago)

    def finish(self, step, run="r1", seconds=2.0, ago=3):
        return self.add("step.finished", {"step": step, "run": run, "seconds": seconds}, ago)

    def fail(self, step, run="r1", error="boom", ago=3):
        return self.add("step.failed", {"step": step, "run": run, "error": error}, ago)


def flow(stage, status="open", log=None, audience="staff"):
    case = {"case_id": "C1", "stage": stage, "status": status}
    return build_flow(case, (log or Log()).events, audience, NOW)


def states(result):
    return [a["state"] for a in result["agents"]]


def agent(result, name):
    return next(a for a in result["agents"] if a["name"] == name)


# ---------- where each stage puts the case ----------

@pytest.mark.parametrize("stage,expected", [
    ("created",                  [PENDING, PENDING, PENDING, PENDING, PENDING, PENDING, PENDING]),
    ("purchase_request_created", [DONE, PENDING, PENDING, PENDING, PENDING, PENDING, PENDING]),
    ("sourcing_needed",          [DONE, DONE, PENDING, PENDING, PENDING, PENDING, PENDING]),
    ("awaiting_quotes",          [DONE, DONE, WAITING, PENDING, PENDING, PENDING, PENDING]),
    ("sourcing_stalled",         [DONE, DONE, NEEDS, PENDING, PENDING, PENDING, PENDING]),
    ("vendor_selected",          [DONE, DONE, DONE, PENDING, PENDING, PENDING, PENDING]),
    ("awaiting_approval",        [DONE, DONE, DONE, NEEDS, PENDING, PENDING, PENDING]),
    ("approved",                 [DONE, DONE, DONE, DONE, PENDING, PENDING, PENDING]),
    ("po_send_failed",           [DONE, DONE, DONE, DONE, NEEDS, PENDING, PENDING]),
    ("po_issued",                [DONE, DONE, DONE, DONE, DONE, WAITING, PENDING]),
    ("delivery_late",            [DONE, DONE, DONE, DONE, DONE, NEEDS, PENDING]),
    ("delivered",                [DONE, DONE, DONE, DONE, DONE, DONE, WAITING]),
])
def test_each_stage_puts_the_case_at_the_right_agent(stage, expected):
    assert states(flow(stage)) == expected


def test_enough_stock_skips_everything_after_the_stock_check():
    assert states(flow("fulfilled_from_stock", "closed")) == [DONE, DONE] + [SKIPPED] * 5


def test_a_rejection_stops_at_approval_and_skips_the_rest():
    assert states(flow("rejected", "closed")) == [DONE, DONE, DONE, STOPPED] + [SKIPPED] * 3


def test_a_completed_case_is_all_done():
    assert states(flow("completed", "closed")) == [DONE] * 7


def test_a_closed_case_at_a_stage_we_do_not_know_is_still_all_done():
    assert states(flow("some_future_stage", "closed")) == [DONE] * 7


def test_an_open_case_at_an_unknown_stage_carries_on_after_the_furthest_finished_step():
    log = Log().start("read_request", "a").finish("read_request", "a").start("check_stock", "b").finish("check_stock", "b")
    assert states(flow("some_future_stage", "open", log)) == [DONE, DONE, PENDING, PENDING, PENDING, PENDING, PENDING]


# ---------- an agent is only "working" while a step is actually running ----------

def test_a_running_step_makes_that_agent_work_and_names_what_it_is_doing():
    log = Log().start("check_stock").progress("check_stock", 1, 3, "Laptop")
    r = flow("purchase_request_created", log=log)
    node = agent(r, "Procurement Agent")
    assert node["state"] == WORKING and node["label"] == "Checking stock"
    assert node["progress"] == {"done": 1, "total": 3, "text": "Laptop"}
    assert r["active_agent"] == "Procurement Agent" and r["headline"] == "Checking stock (1 of 3)…"


def test_a_finished_step_stops_the_agent_working():
    log = Log().start("check_stock").finish("check_stock", seconds=2.5)
    node = agent(flow("sourcing_needed", log=log), "Procurement Agent")
    assert node["state"] == DONE and node["seconds"] == 2.5 and node["runs"] == 1


def test_a_step_that_never_finished_stops_looking_busy_after_ten_minutes():
    stale = Log().start("check_stock", ago=11 * 60)
    fresh = Log().start("check_stock", ago=60)
    assert agent(flow("purchase_request_created", log=stale), "Procurement Agent")["state"] == PENDING
    assert agent(flow("purchase_request_created", log=fresh), "Procurement Agent")["state"] == WORKING


def test_an_agent_can_work_while_the_case_is_waiting_on_suppliers():
    log = Log().start("read_quote")
    node = agent(flow("awaiting_quotes", log=log), "Vendor Agent")
    assert node["state"] == WORKING and node["label"] == "Reading a supplier's quote"


def test_several_runs_of_one_step_are_counted_and_timed_together():
    log = (Log().start("read_quote", "a").finish("read_quote", "a", seconds=1.5)
           .start("read_quote", "b").finish("read_quote", "b", seconds=2.0))
    node = agent(flow("awaiting_quotes", log=log), "Vendor Agent")
    assert node["runs"] == 2 and node["seconds"] == 3.5 and node["state"] == WAITING


def test_only_the_agent_whose_step_is_running_works():
    log = Log().start("rank_quotes")
    assert [a["name"] for a in flow("awaiting_quotes", log=log)["agents"] if a["state"] == WORKING] == ["Vendor Agent"]


# ---------- failures ----------

def test_a_failed_step_shows_failed_when_the_case_has_not_moved_past_it():
    log = Log().start("read_request").fail("read_request", error="AI is down")
    r = flow("created", log=log)
    assert agent(r, "Purchase Agent")["state"] == FAILED


def test_a_failure_that_was_later_retried_successfully_is_not_shown():
    log = Log().start("read_request", "a").fail("read_request", "a").start("read_request", "b").finish("read_request", "b")
    assert agent(flow("purchase_request_created", log=log), "Purchase Agent")["state"] == DONE


def test_a_failed_step_never_hides_a_person_being_needed():
    log = Log().start("rank_quotes").fail("rank_quotes")
    assert agent(flow("sourcing_stalled", log=log), "Vendor Agent")["state"] == NEEDS


# ---------- the invoice's own result ----------

def test_a_mismatched_invoice_needs_a_person_even_though_the_stage_has_not_changed():
    log = Log().add("invoice.mismatch")
    r = flow("delivered", log=log)
    assert agent(r, "Invoice Agent")["state"] == NEEDS and r["needs_person"] is True and r["outcome"] == "needs_person"


def test_an_invoice_that_arrived_before_the_goods_waits():
    assert agent(flow("po_issued", log=Log().add("invoice.on_hold")), "Invoice Agent")["state"] == WAITING


def test_a_closed_case_ignores_invoice_signals():
    assert agent(flow("completed", "closed", Log().add("invoice.mismatch")), "Invoice Agent")["state"] == DONE


# ---------- wording ----------

def test_approval_says_whether_a_machine_or_a_person_approved():
    auto = flow("approved", log=Log().add("approval.auto_approved"))
    manual = flow("approved", log=Log().add("approval.approved"))
    assert agent(auto, "Approval Agent")["label"] == "Approved automatically"
    assert agent(manual, "Approval Agent")["label"] == "Approved"


def test_requesters_and_staff_get_different_wording_for_the_same_problem():
    requester = flow("sourcing_stalled", audience="requester")
    staff = flow("sourcing_stalled", audience="staff")
    assert agent(requester, "Vendor Agent")["label"] == "Taking longer than usual. Our team has been told."
    assert agent(staff, "Vendor Agent")["label"] == "No supplier replied in time. Follow up with suppliers."
    assert requester["headline"] != staff["headline"]


def test_a_requester_gets_no_internal_detail():
    log = (Log().start("check_stock", detail="3 lines: Laptop, Mouse, Rack").progress("check_stock", 1, 3, "Laptop")
           .fail("check_stock", error="Azure OpenAI timed out at https://secret.example"))
    for state_stage in ("purchase_request_created",):
        r = flow(state_stage, log=log, audience="requester")
        node = agent(r, "Procurement Agent")
        assert node["detail"] is None and node["error"] is None
        assert "secret" not in str(r) and "Laptop" not in str(r)


def test_a_requester_sees_progress_counts_but_not_what_is_being_processed():
    log = Log().start("check_stock").progress("check_stock", 2, 3, "Server rack")
    node = agent(flow("purchase_request_created", log=log, audience="requester"), "Procurement Agent")
    assert node["progress"] == {"done": 2, "total": 3, "text": None}


def test_staff_do_get_the_detail_and_the_error():
    log = Log().start("read_request", detail="from the form").fail("read_request", error="AI is down")
    node = agent(flow("created", log=log, audience="staff"), "Purchase Agent")
    assert node["error"] == "AI is down" and node["detail"] == "from the form"


def test_a_requester_is_not_told_why_an_invoice_is_being_checked():
    r = flow("delivered", log=Log().add("invoice.mismatch"), audience="requester")
    assert agent(r, "Invoice Agent")["label"] == "Our team is checking the paperwork"


# ---------- the whole-case summary ----------

@pytest.mark.parametrize("stage,status,outcome", [
    ("awaiting_quotes", "open", "active"), ("awaiting_approval", "open", "needs_person"),
    ("fulfilled_from_stock", "closed", "fulfilled"), ("rejected", "closed", "rejected"),
    ("completed", "closed", "completed"), ("po_issued", "open", "active")])
def test_the_outcome_summarises_the_case(stage, status, outcome):
    assert flow(stage, status)["outcome"] == outcome


def test_the_active_agent_is_the_one_working_otherwise_the_one_waiting_or_needing_help():
    assert flow("awaiting_quotes")["active_agent"] == "Vendor Agent"
    assert flow("awaiting_approval")["active_agent"] == "Approval Agent"
    assert flow("completed", "closed")["active_agent"] is None


def test_there_is_always_one_node_per_flow_agent_in_order():
    r = flow("po_issued")
    assert [a["name"] for a in r["agents"]] == list(FLOW_AGENTS)
    assert [a["key"] for a in r["agents"]] == ["purchase", "procurement", "vendor", "approval", "po", "delivery", "invoice"]


def test_every_state_has_a_label_a_requester_can_read():
    for stage in ("created", "awaiting_quotes", "sourcing_stalled", "awaiting_approval", "po_send_failed",
                  "po_issued", "delivery_late", "delivered", "completed", "rejected", "fulfilled_from_stock"):
        r = flow(stage, "closed" if stage in ("completed", "rejected", "fulfilled_from_stock") else "open", audience="requester")
        assert r["headline"] and all(a["label"] for a in r["agents"]), stage


def test_headline_for_covers_every_stage_the_pipeline_can_set():
    for stage in ("created", "awaiting_quotes", "po_issued", "delivered", "completed", "rejected"):
        assert headline_for(stage, "open")
    assert headline_for("brand_new_stage", "closed") == "This request is complete."
    assert headline_for("brand_new_stage", "open") == "Your request is in progress."


# ---------- driven by the real flow ----------

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def live(w: World, case_id: str, audience="staff"):
    case = {"case_id": case_id, "stage": w.stage(case_id), "status": w.cases[case_id].status}
    events = [{"event_id": e.event_id, "event_type": e.event_type, "agent_name": e.agent_name,
               "payload": e.payload, "created_at": e.created_at} for e in w.events.get(case_id, [])]
    from app.core.agent_flow import build_flow as build
    return build(case, events, audience, utc_now())


def test_an_agent_really_is_working_while_it_is_in_the_middle_of_its_step(w, monkeypatch):
    """Look at the state from INSIDE the Purchase Agent's step: it must say it is working, then done."""
    seen = {}
    real = purchase_agent.create_purchase_request

    def spy(case_id, raw_request, **kw):
        seen["during"] = agent(live(w, case_id), "Purchase Agent")["state"]
        return real(case_id=case_id, raw_request=raw_request, **kw)

    monkeypatch.setattr(case_pipeline.purchase_agent, "create_purchase_request", spy)
    case_id = w.submit("50 cameras")
    assert seen["during"] == WORKING
    assert agent(live(w, case_id), "Purchase Agent")["state"] == DONE


def test_a_real_request_waiting_on_suppliers_looks_right(w):
    case_id = w.submit("50 cameras")
    r = live(w, case_id, "requester")
    assert states(r) == [DONE, DONE, WAITING, PENDING, PENDING, PENDING, PENDING]
    assert agent(r, "Vendor Agent")["label"] == "Waiting for suppliers to reply"
    assert r["headline"] == headline_for("awaiting_quotes", "open")


def test_a_real_request_from_start_to_finish_ends_with_every_agent_done(w):
    case_id = w.submit("50 cameras")
    for vendor, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30",
                         "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, vendor, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    assert states(live(w, case_id)) == [DONE, DONE, DONE, DONE, DONE, WAITING, PENDING]
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)
    w.reply(case_id, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.",
            subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    final = live(w, case_id)
    assert states(final) == [DONE] * 7 and final["outcome"] == "completed"
    assert agent(final, "Approval Agent")["label"] == "Approved automatically"
    assert all(a["seconds"] is not None for a in final["agents"] if a["runs"])   # every step that ran was timed
    assert agent(final, "Purchase Agent")["runs"] == 1 and agent(final, "Vendor Agent")["runs"] == 4


def test_enough_stock_in_the_real_flow_skips_the_suppliers(w):
    case_id = w.submit("10 laptops")
    r = live(w, case_id, "requester")
    assert states(r) == [DONE, DONE] + [SKIPPED] * 5 and r["outcome"] == "fulfilled"


def test_an_old_case_with_no_step_signals_still_draws_correctly(w):
    case_id = w.submit("50 cameras")
    w.events[case_id] = [e for e in w.events[case_id] if not e.event_type.startswith("step.")]   # as before this feature
    assert states(live(w, case_id)) == [DONE, DONE, WAITING, PENDING, PENDING, PENDING, PENDING]


# ---------- over HTTP: who may see what ----------

@pytest.fixture
def people(monkeypatch):
    users = {
        "alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
    }
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    mine, theirs = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"
    owners = {mine: "alice@x.co", theirs: "bob@x.co"}
    monkeypatch.setattr("app.core.case_access.case_repository.find_case_by_id",
                        lambda cid: SimpleNamespace(requester_id=owners[cid]) if cid in owners else None)
    ops = agent_flow_controller.operations_agent
    asked = []
    monkeypatch.setattr(ops, "get_all_cases", lambda requester_id=None: asked.append(requester_id) or [
        {"case_id": c, "requester_id": o, "stage": "awaiting_quotes", "status": "open",
         "items_summary": "Camera (50)", "updated_at": NOW} for c, o in owners.items()
        if requester_id is None or o == requester_id])
    monkeypatch.setattr(ops, "get_case_status", lambda cid: {"case_id": cid, "requester_id": owners[cid], "stage": "purchase_request_created", "status": "open"})
    from app.core.exceptions import PurchaseOrderNotFound as _NoOrder

    def _no_order(cid):
        raise _NoOrder(cid)
    monkeypatch.setattr(agent_flow_controller.delivery_agent, "get_delivery", _no_order)
    monkeypatch.setattr(agent_flow_controller.purchase_agent, "get_purchase_request", lambda cid: {
        "raw_request": "We need 50 CCTV cameras for Pune", "cost_center": "OPS-7", "created_at": NOW,
        "items": [{"description": "CCTV camera", "quantity": 50}]})
    monkeypatch.setattr(ops, "get_case_events", lambda cid: Log()
                        .start("check_stock", detail="SECRET DETAIL").fail("check_stock", error="SECRET ERROR").events)
    access.invalidate()
    yield mine, theirs, asked
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_the_page_needs_a_login():
    assert client.get("/agent-flow/cases").status_code == 401


def test_a_requester_only_lists_their_own_cases(people):
    mine, theirs, asked = people
    body = client.get("/agent-flow/cases", headers=as_("alice", "user")).json()
    assert [c["case_id"] for c in body] == [mine] and asked == ["alice@x.co"]
    assert body[0]["requester"] is None                    # who asked is staff-only


def test_staff_list_every_case_with_who_asked(people):
    mine, theirs, _ = people
    body = client.get("/agent-flow/cases", headers=as_("mgr", "manager")).json()
    assert {c["case_id"] for c in body} == {mine, theirs} and {c["requester"] for c in body} == {"alice@x.co", "bob@x.co"}


def test_a_requester_cannot_open_someone_elses_flow(people):
    _, theirs, _ = people
    assert client.get(f"/agent-flow/cases/{theirs}", headers=as_("alice", "user")).status_code == 404


def test_a_requester_gets_the_flow_with_no_internal_detail(people):
    mine, _, _ = people
    r = client.get(f"/agent-flow/cases/{mine}", headers=as_("alice", "user"))
    assert r.status_code == 200 and r.json()["audience"] == "requester"
    assert "SECRET" not in r.text


def test_the_request_is_shown_in_full_and_who_asked_is_staff_only(people):
    mine, _, _ = people
    requester = client.get(f"/agent-flow/cases/{mine}", headers=as_("alice", "user")).json()["request"]
    assert requester["raw_text"] == "We need 50 CCTV cameras for Pune" and requester["cost_center"] == "OPS-7"
    assert requester["items"] == [{"description": "CCTV camera", "quantity": 50}] and requester["requested_by"] is None
    staff = client.get(f"/agent-flow/cases/{mine}", headers=as_("mgr", "manager")).json()["request"]
    assert staff["requested_by"] == "alice@x.co"


def test_a_case_with_no_recorded_request_still_loads(people, monkeypatch):
    mine, _, _ = people
    from app.core.exceptions import PurchaseRequestNotFound

    def missing(cid):
        raise PurchaseRequestNotFound(cid)
    monkeypatch.setattr(agent_flow_controller.purchase_agent, "get_purchase_request", missing)
    r = client.get(f"/agent-flow/cases/{mine}", headers=as_("alice", "user"))
    assert r.status_code == 200 and r.json()["request"] is None


def test_staff_get_the_detail(people):
    mine, _, _ = people
    body = client.get(f"/agent-flow/cases/{mine}", headers=as_("mgr", "manager")).json()
    procurement = next(a for a in body["agents"] if a["key"] == "procurement")
    assert body["audience"] == "staff" and procurement["error"] == "SECRET ERROR" and procurement["detail"] == "SECRET DETAIL"


def test_next_step_points_at_the_first_agent_not_yet_started():
    assert flow("awaiting_quotes")["next_step"] == "The order will be checked, and a person signs off if it needs one."  # vendor is under way
    assert flow("purchase_request_created")["next_step"] == "We'll check whether it is already in stock."


def test_next_step_is_empty_once_the_case_is_closed():
    assert flow("completed", status="closed")["next_step"] is None
    assert flow("fulfilled_from_stock", status="closed")["next_step"] is None


def test_next_step_wording_is_the_same_for_a_requester_and_staff():
    assert flow("awaiting_quotes", audience="requester")["next_step"] == flow("awaiting_quotes", audience="staff")["next_step"]


def test_support_agents_report_the_record_and_the_emails():
    log = Log().add("stage.created").add("notification.sent", {"kind": "approval_needed", "sent": 2, "failed": 0})
    ops, notify = flow("awaiting_approval", log=log)["support"]
    assert ops["state"] == "active" and "2 so far" in ops["label"]
    assert notify["state"] == "done" and notify["label"] == "Emailed 2 people who can approve"
    # a requester is only told that someone was told: no counts, no addresses
    assert flow("awaiting_approval", log=log, audience="requester")["support"][1]["label"] == "A person has been told"


def test_support_notification_flags_when_nobody_could_be_reached():
    log = Log().add("notification.no_recipients", {"kind": "case_stalled"})
    assert flow("awaiting_approval", log=log)["support"][1]["state"] == "attention"
    assert flow("awaiting_approval")["support"][1]["state"] == "idle"


def test_support_operations_is_done_once_the_case_closes():
    assert flow("completed", status="closed")["support"][0]["state"] == "done"


def test_the_delivery_date_shows_while_the_goods_are_awaited():
    from datetime import date
    from app.core.agent_flow import apply_expected_delivery
    result = flow("po_issued")
    assert next(a for a in result["agents"] if a["key"] == "delivery")["state"] == "waiting"
    apply_expected_delivery(result, date(2026, 10, 7), date(2026, 10, 2))
    assert next(a for a in result["agents"] if a["key"] == "delivery")["label"] == "Expected by 7 Oct"
    assert result["expected_delivery"] == date(2026, 10, 7)


def test_a_late_delivery_says_overdue():
    from datetime import date
    from app.core.agent_flow import apply_expected_delivery
    result = flow("po_issued")
    apply_expected_delivery(result, date(2026, 10, 7), date(2026, 10, 9))
    assert next(a for a in result["agents"] if a["key"] == "delivery")["label"] == "Overdue: was due 7 Oct"


def test_the_date_leaves_a_delivered_or_not_yet_ordered_case_alone():
    from datetime import date
    from app.core.agent_flow import apply_expected_delivery
    done = flow("completed", status="closed")
    before = next(a for a in done["agents"] if a["key"] == "delivery")["label"]
    apply_expected_delivery(done, date(2026, 10, 7), date(2026, 10, 9))
    assert next(a for a in done["agents"] if a["key"] == "delivery")["label"] == before
    early = flow("awaiting_quotes")
    apply_expected_delivery(early, None, date(2026, 10, 2))
    assert early["expected_delivery"] is None


def test_a_requester_also_gets_the_expected_delivery(people, monkeypatch):
    from datetime import date
    mine, _, _ = people
    monkeypatch.setattr(agent_flow_controller.delivery_agent, "get_delivery", lambda cid: {"expected_delivery_date": date(2026, 10, 7)})
    body = client.get(f"/agent-flow/cases/{mine}", headers=as_("alice", "user")).json()
    assert body["expected_delivery"] == "2026-10-07"
