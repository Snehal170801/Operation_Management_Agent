from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import my_work_controller
from app.core import access, security
from app.core.my_work import build_my_work
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, DEPARTMENTS
from app.main import app
from app.repositories import role_repository, user_repository

NOW = datetime(2026, 10, 2, 12, 0)
client = TestClient(app)


def case(n, stage="po_issued", status="open", requester="alice@x.co", age=timedelta(hours=1)):
    return {"case_id": f"c{n}", "case_number": f"REQ-2026-000{n}", "items_summary": f"Item {n}", "stage": stage, "status": status,
            "requester_id": requester, "updated_at": NOW - age}


CASES = [case(1, "awaiting_approval"), case(2, "po_issued"), case(3, "sourcing_stalled"), case(4, "po_send_failed"),
         case(5, "created", age=timedelta(minutes=10)), case(6, "created", age=timedelta(seconds=20)), case(7, "po_issued", requester="mgr@x.co")]
APPROVALS = [{"approval_id": "a1", "case_id": "c1", "reasons": ["Amount too high."], "created_at": NOW},
             {"approval_id": "a2", "case_id": "c7", "reasons": ["Only 1 quote."], "created_at": NOW}]
DELIVERIES = [{"purchase_order_id": "p1", "po_number": "PO-1001", "case_id": "c2", "vendor_name": "Acme", "chase_count": 2,
               "expected_delivery_date": date(2026, 9, 28), "escalated_at": NOW},
              {"purchase_order_id": "p2", "po_number": "PO-1002", "case_id": "c7", "vendor_name": "Globex", "chase_count": 0,
               "expected_delivery_date": date(2026, 10, 7), "escalated_at": None}]
INVOICES = [{"invoice_id": "i1", "case_id": "c2", "invoice_number": "INV-1", "total_amount": 45000.0, "status": "mismatch",
             "issues": ["Invoice total 45,000.00 differs from the purchase order total 38,000.00."], "created_at": NOW},
            {"invoice_id": "i2", "case_id": "c7", "invoice_number": "INV-2", "total_amount": 1000.0, "status": "on_hold", "issues": [], "created_at": NOW}]
STOCK = [{"item_description": "Projector", "quantity_available": 4, "updated_at": NOW},
         {"item_description": "Laptop", "quantity_available": 0, "updated_at": NOW},
         {"item_description": "Mouse", "quantity_available": 300, "updated_at": NOW}]


def work(perms, user="mgr@x.co"):
    return build_my_work(user, lambda p: p in perms, APPROVALS, CASES, DELIVERIES, INVOICES, STOCK, NOW)


def queue(result, key):
    return next(q for q in result["queues"] if q["key"] == key)


def titles(result, key):
    return [i["title"] for i in queue(result, key)["items"]]


def test_a_department_sees_only_its_own_queue():
    for perms, key in ((("approvals:write",), "approval"), (("delivery:confirm",), "delivery"), (("invoices:decide",), "invoice"),
                       (("vendors:write",), "vendor"), (("po:manage",), "po"), (("cases:write",), "purchase"), (("stock:write",), "stores")):
        assert [q["key"] for q in work(set(perms))["queues"]] == [key]


def test_nobody_with_no_job_sees_anything():
    assert work(set()) == {"total": 0, "queues": []}


def test_the_admin_who_holds_everything_sees_every_queue_and_a_person_in_two_departments_sees_two():
    assert [q["key"] for q in work(ALL_PERMISSIONS)["queues"]] == ["approval", "delivery", "invoice", "vendor", "po", "purchase", "stores"]
    assert [q["key"] for q in work({"delivery:confirm", "invoices:decide"})["queues"]] == ["delivery", "invoice"]


def test_approvers_see_why_and_are_told_when_it_is_their_own_request():
    items = {i["id"]: i for i in queue(work({"approvals:write"}), "approval")["items"]}
    assert items["approval:a1"]["title"] == "REQ-2026-0001 · Item 1" and items["approval:a1"]["detail"] == "Amount too high."
    assert items["approval:a1"]["note"] is None
    assert "someone else has to approve" in items["approval:a2"]["note"]          # mgr@x.co asked for case 7


def test_receiving_sees_overdue_deliveries_first_with_how_late_and_how_often_chased():
    items = queue(work({"delivery:confirm"}), "delivery")["items"]
    assert items[0]["urgent"] and "Overdue by 4 day(s)" in items[0]["detail"] and "chased 2 time(s)" in items[0]["detail"]
    assert not items[1]["urgent"] and "Expected 7 Oct" in items[1]["detail"]
    assert items[0]["link"] == "/cases/c2"


def test_accounts_see_mismatches_urgently_and_held_invoices_as_waiting_on_receiving():
    items = queue(work({"invoices:decide"}), "invoice")["items"]
    assert items[0]["urgent"] and "differs from the purchase order total" in items[0]["detail"] and "₹45,000" in items[0]["title"]
    assert not items[1]["urgent"] and "Receiving" in items[1]["detail"] and items[1]["action"] == "See case"


def test_vendor_po_and_purchase_queues_pick_the_right_stuck_cases():
    assert titles(work({"vendors:write"}), "vendor") == ["REQ-2026-0003 · Item 3"]
    assert titles(work({"po:manage"}), "po") == ["REQ-2026-0004 · Item 4"]
    # case 5 has sat unread for 10 minutes; case 6 was only created 20 seconds ago, so the AI is probably still reading it
    assert titles(work({"cases:write"}), "purchase") == ["REQ-2026-0005 · Item 5"]


def test_closed_cases_never_appear():
    closed = [case(3, "sourcing_stalled", status="closed"), case(4, "po_send_failed", status="closed")]
    result = build_my_work("a", lambda p: True, [], closed, [], [], [], NOW)
    assert titles(result, "vendor") == [] and titles(result, "po") == []


def test_stores_see_low_and_empty_stock_with_empty_first():
    items = queue(work({"stock:write"}), "stores")["items"]
    assert [i["title"] for i in items] == ["Laptop", "Projector"]
    assert items[0]["urgent"] and items[0]["detail"] == "Out of stock" and items[1]["detail"] == "Only 4 left"


def test_the_total_counts_every_item_across_the_queues():
    result = work({"approvals:write", "delivery:confirm"})
    assert result["total"] == len(queue(result, "approval")["items"]) + len(queue(result, "delivery")["items"]) == 4


# --------------------------------------------------------------------------------------------- the endpoint

@pytest.fixture
def people(monkeypatch):
    users = {d.key: SimpleNamespace(user_id=d.key, username=f"{d.key}@x.co", role=f"dept_{d.key}", is_active=True) for d in DEPARTMENTS}
    users["requester"] = SimpleNamespace(user_id="requester", username="r@x.co", role="user", is_active=True)
    roles = {f"dept_{d.key}": set(d.permissions) for d in DEPARTMENTS}
    roles.update({"user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: roles)
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    c = my_work_controller
    seen = {"cases": 0, "invoices": 0, "stock": 0}
    monkeypatch.setattr(c.operations_agent, "get_all_cases", lambda r=None: seen.__setitem__("cases", seen["cases"] + 1) or CASES)
    monkeypatch.setattr(c.approval_agent, "get_approvals", lambda status=None, case_id=None: APPROVALS)
    monkeypatch.setattr(c.delivery_agent, "get_open_deliveries", lambda: DELIVERIES)
    monkeypatch.setattr(c.delivery_agent, "get_open_disputes", lambda: {})
    monkeypatch.setattr(c.invoice_agent, "list_invoices", lambda status=None: seen.__setitem__("invoices", seen["invoices"] + 1) or [i for i in INVOICES if status in (None, i["status"])])
    monkeypatch.setattr(c.procurement_agent, "get_all_stock", lambda: seen.__setitem__("stock", seen["stock"] + 1) or STOCK)
    monkeypatch.setattr(c, "attach_suggestions", lambda invoices: invoices)       # (the sentences are tested on their own)
    access.invalidate()
    yield seen
    access.invalidate()


def as_(who):
    role = "user" if who == "requester" else f"dept_{who}"
    token, _ = security.create_access_token(who, f"{who}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_the_page_needs_a_login_and_a_requester_has_no_queue():
    assert client.get("/my-work").status_code == 401


def test_a_requester_cannot_open_it(people):
    assert client.get("/my-work", headers=as_("requester")).status_code == 403


def test_receiving_gets_only_deliveries_and_the_server_reads_only_what_it_needs(people):
    body = client.get("/my-work", headers=as_("delivery")).json()
    assert [q["key"] for q in body["queues"]] == ["delivery"] and body["total"] == 2
    assert people["invoices"] == 0 and people["stock"] == 0        # nothing was read that Receiving never sees


def test_accounts_get_only_invoices(people):
    body = client.get("/my-work", headers=as_("invoice")).json()
    assert [q["key"] for q in body["queues"]] == ["invoice"] and body["total"] == 2 and people["stock"] == 0


# ---- countdown to escalation -------------------------------------------------------------------------------------------

def work_escalating(perms, hours=24):
    return build_my_work("mgr@x.co", lambda p: p in perms, APPROVALS, CASES, DELIVERIES, INVOICES, STOCK, NOW, escalate_after_hours=hours)


def test_work_the_escalation_rule_covers_shows_when_the_admin_will_be_told():
    items = {i["id"]: i for i in queue(work_escalating({"approvals:write"}), "approval")["items"]}
    assert items["approval:a1"]["escalates_at"] == NOW + timedelta(hours=24)        # created NOW, so 24 h from NOW
    stalled = queue(work_escalating({"vendors:write"}), "vendor")["items"][0]
    assert stalled["escalates_at"] == stalled["since"] + timedelta(hours=24)


def test_only_a_mismatched_invoice_counts_down_not_one_that_is_just_waiting_for_the_goods():
    items = {i["id"]: i for i in queue(work_escalating({"invoices:decide"}), "invoice")["items"]}
    assert items["invoice:i1"]["escalates_at"] is not None       # mismatch: the rule covers it
    assert items["invoice:i2"]["escalates_at"] is None           # on hold for goods: nothing escalates it


def test_no_countdown_when_escalation_is_switched_off_or_for_work_it_does_not_cover():
    assert all(i["escalates_at"] is None for q in work_escalating(ALL_PERMISSIONS, hours=0)["queues"] for i in q["items"])
    covered = {"approval", "vendor", "po", "invoice"}
    for q in work_escalating(ALL_PERMISSIONS)["queues"]:
        if q["key"] not in covered:
            assert all(i["escalates_at"] is None for i in q["items"])


def test_the_internal_marker_never_leaks_into_the_answer():
    assert all("_escalates" not in i for q in work_escalating(ALL_PERMISSIONS)["queues"] for i in q["items"])
