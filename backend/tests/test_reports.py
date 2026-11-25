"""The management report: spend, stage times, how much ran with no person, supplier scorecards."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import report_controller
from app.core import access, security
from app.core.permissions import ALL_PERMISSIONS, DEPARTMENTS
from app.core.reports import build_report
from app.main import app
from app.repositories import report_repository, role_repository, user_repository

NOW = datetime(2026, 10, 10, 12)


def t(days=0, hours=0):
    return datetime(2026, 10, 1, 9) + timedelta(days=days, hours=hours)


def case(cid, stage, status="closed", created=None, updated=None):
    return {"case_id": cid, "case_number": f"REQ-{cid}", "stage": stage, "status": status, "created_at": created or t(), "updated_at": updated or t(1)}


def ev(cid, kind, when, **payload):
    return {"case_id": cid, "event_type": kind, "payload": payload, "created_at": when}


def po(cid, vendor, amount, created, **over):
    return {"case_id": cid, "vendor_id": vendor.lower(), "vendor_name": vendor, "total_amount": amount, "created_at": created, "sent_at": created,
            "status": "sent", "expected_delivery_date": None, "delivered_at": None, "delivery_status": "pending", "acknowledged_at": None, **over}


def rfq(cid, vendor, sent, replied=None):
    return {"case_id": cid, "vendor_id": vendor.lower(), "vendor_name": vendor, "sent_at": sent, "replied_at": replied, "status": "replied" if replied else "sent"}


def world():
    """A: ran with no person, in stock. B: no person, full cycle. C: needed a person twice. D: still open and stuck."""
    cases = [case("a", "fulfilled_from_stock"), case("b", "completed", created=t(0)), case("c", "completed", created=t(1)),
             case("d", "awaiting_quotes", "open", created=t(2), updated=NOW - timedelta(hours=30))]
    events = [
        ev("b", "rfq.sent", t(0, 1)), ev("b", "vendor.selected", t(0, 5)), ev("b", "po.issued", t(0, 6)), ev("b", "po.confirmed", t(0, 8), via="email"),
        ev("b", "delivery.received", t(3, 6)), ev("b", "invoice.matched", t(3, 8)), ev("b", "case.closed", t(3, 8)),
        ev("c", "rfq.sent", t(1, 1)), ev("c", "sourcing.stalled", t(2, 1)), ev("c", "approval.requested", t(2, 3)), ev("c", "vendor.selected", t(1, 20)),
        ev("c", "po.issued", t(2, 12)), ev("c", "po.vendor_problem", t(2, 14)), ev("c", "delivery.received", t(6, 0)), ev("c", "invoice.approved", t(6, 3)),
        ev("c", "case.closed", t(6, 3)),
        ev("d", "step.failed", t(2, 1), step="read_quote"),
    ]
    rfqs = [rfq("b", "Acme", t(0, 1), t(0, 3)), rfq("b", "Globex", t(0, 1), t(0, 5)), rfq("c", "Acme", t(1, 1)), rfq("c", "Globex", t(1, 1), t(1, 7))]
    pos = [po("b", "Acme", 40000.0, t(0, 6), acknowledged_at=t(0, 8), expected_delivery_date=date(2026, 10, 4), delivery_status="delivered", delivered_at=t(3, 6)),
           po("c", "Globex", 60000.0, t(2, 12), expected_delivery_date=date(2026, 10, 5), delivery_status="delivered", delivered_at=t(6, 0))]
    invoices = [{"case_id": "b", "vendor_id": "acme", "status": "matched"}, {"case_id": "c", "vendor_id": "globex", "status": "mismatch"},
                {"case_id": "c", "vendor_id": "globex", "status": "approved"}]
    return build_report(cases, events, rfqs, pos, invoices, NOW, 30)


def test_totals_and_spend():
    r = world()
    # b started 1 Oct 09:00 and closed 4 Oct 17:00 (80 h); c started 2 Oct 09:00 and closed 7 Oct 12:00 (123 h)
    assert r["totals"] == {"requests": 4, "completed": 2, "from_stock": 1, "rejected": 0, "cancelled": 0, "in_progress": 1, "spend": 100000.0, "orders": 2, "avg_cycle_hours": 101.5}
    assert r["spend"]["by_vendor"] == [{"vendor": "Globex", "total": 60000.0, "orders": 1}, {"vendor": "Acme", "total": 40000.0, "orders": 1}]
    assert r["spend"]["by_month"] == [{"month": "2026-10", "total": 100000.0, "orders": 2}]


def test_how_much_ran_with_no_person_and_who_got_stuck():
    a = world()["automation"]
    assert (a["touchless"], a["needed_a_person"], a["in_progress_so_far_clean"]) == (2, 2, 0)   # a and b ran alone; c and d needed someone
    assert a["touchless_pct"] == 50
    by = {x["agent"]: x for x in a["by_agent"]}
    assert (by["Vendor"]["cases"], by["Approval"]["cases"], by["PO"]["cases"]) == (2, 1, 1)       # c stalled at the Vendor agent, d's failed step was too
    assert {r["label"] for r in by["Vendor"]["reasons"]} == {"No supplier replied in time", "A step failed"}
    assert {r["label"] for r in by["PO"]["reasons"]} == {"The supplier raised a problem with the order"}
    assert a["by_agent"][0]["agent"] == "Vendor"                                                  # the agent that needed a person most comes first


def test_a_failed_step_is_blamed_on_the_agent_that_ran_it():
    r = build_report([case("d", "awaiting_quotes", "open")], [ev("d", "step.failed", t(), step="read_quote")], [], [], [], NOW, 30)
    assert [(x["agent"], x["cases"]) for x in r["automation"]["by_agent"]] == [("Vendor", 1)]


def test_how_long_each_stage_takes():
    steps = {s["label"]: s for s in world()["stage_times"]}
    one = steps["Asking suppliers until a supplier is chosen"]
    assert (one["avg_hours"], one["count"]) == (11.5, 2)                                           # b took 4 h, c took 19 h
    two = steps["Order placed until the supplier confirms"]
    assert (two["avg_hours"], two["count"]) == (2.0, 1)                                           # only b was confirmed by email
    three = steps["Order placed until the goods are received"]
    assert (three["avg_hours"], three["count"]) == (78.0, 2)                                       # b 72 h, c 84 h
    four = steps["Whole request, start to finish"]
    assert (four["avg_hours"], four["count"]) == (101.5, 2)


def test_where_open_requests_are_stuck():
    stuck = world()["stuck"]
    assert stuck == [{"stage": "awaiting_quotes", "label": "Waiting for supplier quotes", "count": 1, "oldest_hours": 30.0, "avg_hours": 30.0}]


def test_supplier_scorecards():
    s = {x["name"]: x for x in world()["suppliers"]}
    acme, globex = s["Acme"], s["Globex"]
    assert (acme["asked"], acme["replied"], acme["reply_rate"], acme["avg_reply_hours"]) == (2, 1, 50, 2.0)
    assert (globex["asked"], globex["replied"], globex["reply_rate"], globex["avg_reply_hours"]) == (2, 2, 100, 5.0)   # answered in 4 h and 6 h
    assert acme["confirm_rate"] == 100 and acme["avg_confirm_hours"] == 2.0 and globex["confirm_rate"] == 0 and globex["avg_confirm_hours"] is None
    assert (acme["delivered"], acme["late"]) == (1, 0)                                              # due 4 Oct, arrived 4 Oct
    assert (globex["delivered"], globex["late"], globex["avg_days_late"]) == (1, 1, 2.0)           # due 5 Oct, arrived 7 Oct
    assert globex["invoices"] == 2 and globex["invoice_problems"] == 1 and acme["invoice_problems"] == 0
    assert [x["name"] for x in world()["suppliers"]] == ["Globex", "Acme"]                  # biggest spend first


def test_an_open_order_past_its_date_counts_as_late():
    r = build_report([case("x", "po_issued", "open")], [], [], [po("x", "Acme", 1000.0, t(), expected_delivery_date=date(2026, 10, 7))], [], NOW, 30)
    acme = r["suppliers"][0]
    assert (acme["late"], acme["delivered"], acme["avg_days_late"]) == (1, 0, 3.0)


def test_an_empty_period_is_all_zeros_not_an_error():
    r = build_report([], [], [], [], [], NOW, 7)
    assert r["totals"]["requests"] == 0 and r["automation"]["touchless_pct"] is None and r["suppliers"] == [] and r["stuck"] == []
    assert all(s["avg_hours"] is None and s["count"] == 0 for s in r["stage_times"])


# ---- the route ----

@pytest.fixture
def client(monkeypatch):
    users = {u: SimpleNamespace(user_id=u, username=u, role=r, is_active=True, email=None, display_name=u) for u, r in (("adm", "admin"), ("req", "user"), ("recv", "dept_delivery"))}
    roles = {f"dept_{d.key}": set(d.permissions) for d in DEPARTMENTS}
    roles.update({"admin": set(ALL_PERMISSIONS), "user": {"cases:read", "cases:create"}})
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: roles)
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(str(uid).lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    seen = SimpleNamespace(since=[])
    row = lambda **k: SimpleNamespace(**k)
    monkeypatch.setattr(report_repository, "cases_since", lambda since: seen.since.append(since) or [row(case_id="A", case_number="REQ-1", stage="completed", status="closed", created_at=t(), updated_at=t(1))])
    monkeypatch.setattr(report_repository, "rfqs_since", lambda since: [])
    monkeypatch.setattr(report_repository, "purchase_orders_since", lambda since: [])
    monkeypatch.setattr(report_repository, "invoices_since", lambda since: [])
    access.invalidate()
    c = TestClient(app)
    c.seen = seen
    return c


def head(uid):
    return {"Authorization": f"Bearer {security.create_access_token(uid, uid, 'x')[0]}"}


def test_staff_can_open_it_and_a_requester_cannot(client):
    ok = client.get("/reports?days=30", headers=head("adm"))
    assert ok.status_code == 200 and ok.json()["totals"]["requests"] == 1 and ok.json()["days"] == 30
    assert client.get("/reports", headers=head("recv")).status_code == 200            # departments hold the dashboard permission
    assert client.get("/reports", headers=head("req")).status_code == 403
    assert client.get("/reports").status_code == 401


def test_the_period_is_applied_and_all_time_has_no_start(client):
    client.get("/reports?days=7", headers=head("adm"))
    client.get("/reports?days=0", headers=head("adm"))
    assert client.seen.since[-1] is None and client.seen.since[0] is not None
    assert client.get("/reports?days=-1", headers=head("adm")).status_code == 422
    assert client.get("/reports?days=99999", headers=head("adm")).status_code == 422
