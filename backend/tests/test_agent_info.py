from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import agent_flow_controller
from app.core import access, security
from app.core.agent_info import AGENT_KEYS, build_agent_info
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.repositories import role_repository, user_repository

client = TestClient(app)
T = datetime(2026, 10, 2, 11, 30)


def ev(i, event_type, agent=None, payload=None):
    return {"event_id": i, "event_type": event_type, "agent_name": agent, "payload": payload or {}, "created_at": T}


def bundle(**over):
    """A finished case shaped like REQ-2026-0001: three quotes, one chosen, auto-approved, ordered, delivered, invoiced."""
    quote = lambda vid, name, price, days, terms, raw: {"vendor_id": vid, "vendor_name": name, "price": price, "lead_time_days": days,
                                                          "terms": terms, "raw_quote_text": raw, "created_at": T}
    d = {
        "case": {"requester_id": "alice@x.co", "stage": "completed", "status": "closed", "created_at": T},
        "events": [
            ev(1, "case.created", "Operations Agent"), ev(2, "step.started", "Purchase Agent", {"step": "read_request", "run": "a"}),
            ev(3, "step.finished", "Purchase Agent", {"step": "read_request", "run": "a", "seconds": 1.8}),
            ev(4, "stock.checked", "Procurement Agent", {"sufficient": False, "checks": [
                {"description": "ABC fire extinguisher 4kg", "stock_item": None, "requested": 20, "available": 0, "sufficient": False}]}),
            ev(5, "stage.sourcing_needed", "Operations Agent"), ev(6, "vendor.selected", "Vendor Agent", {"ranking": [
                {"vendor_id": "v1", "rank": 1, "reason": "Fast enough and best terms."}, {"vendor_id": "v2", "rank": 2, "reason": "Cheapest but slowest."}]}),
            ev(7, "approval.auto_approved", "Approval Agent"), ev(8, "po.issued", "PO Agent"), ev(9, "delivery.received", "Delivery Agent"),
            ev(10, "invoice.matched", "Invoice Agent"), ev(11, "case.closed", "Operations Agent"),
            ev(12, "notification.sent", "Notification Agent", {"kind": "approval_needed", "sent": 2, "failed": 0}),
        ],
        "request": {"raw_request": "Need 20 ABC fire extinguishers (4 kg)", "cost_center": "OPS-7", "created_at": T,
                    "items": [{"description": "ABC fire extinguisher 4kg", "quantity": 20}]},
        "rfqs": [{"vendor_id": "v1", "vendor_name": "Bhore Shrikrishna", "status": "replied", "sent_at": T, "replied_at": T, "reminder_count": 0, "deadline_at": T},
                 {"vendor_id": "v2", "vendor_name": "Digv Bhore", "status": "replied", "sent_at": T, "replied_at": T, "reminder_count": 1, "deadline_at": T}],
        "quotes": [quote("v1", "Bhore Shrikrishna", 38000.0, 5, "net 30", "Total Rs 38000 Delivery 5 days terms net 30"),
                   quote("v2", "Digv Bhore", 36000.0, 7, "Net 15", "Total Rs 36000 Delivery in 7days Terms Net 15")],
        "selection": {"vendor_id": "v1", "vendor_name": "Bhore Shrikrishna", "rationale": "Best overall: price, lead time, terms, reliability."},
        "vendors": {"v1": {"vendor_id": "v1", "email": "shri@v.co", "reliability_score": 4.2},
                    "v2": {"vendor_id": "v2", "email": "digv@v.co", "reliability_score": 4.2}},
        "approvals": [{"status": "auto_approved", "decided_by": "policy", "decided_at": T, "decision_note": None, "reasons": [], "created_at": T}],
        "po": {"po_number": "PO-1003", "vendor_id": "v1", "vendor_name": "Bhore Shrikrishna", "total_amount": 38000.0, "terms": "net 30",
               "lead_time_days": 5, "expected_delivery_date": "2026-10-07", "status": "sent", "created_at": T, "sent_at": T,
               "items": [{"description": "ABC fire extinguisher 4kg", "quantity": 20}]},
        "delivery": {"po_number": "PO-1003", "delivery_status": "delivered", "expected_delivery_date": "2026-10-07", "chase_count": 0,
                     "last_chased_at": None, "escalated_at": None, "delivered_at": T, "received_by": "mgr@x.co", "delivery_note": "All 20 checked"},
        "invoices": [{"invoice_id": "i1", "vendor_id": "v1", "vendor_name": "Bhore Shrikrishna", "po_number": "PO-1003", "invoice_number": "INV-1001",
                      "total_amount": 38000.0, "status": "matched", "issues": [], "source": "email", "decided_by": None, "decision_note": None,
                      "created_at": T, "raw_text": "Invoice INV-1001 Total Rs 38000", "extracted": {"po_number": "PO-1003", "items": [{"description": "x", "quantity": 20}]}}],
    }
    d.update(over)
    return d


def sections(key, d=None, staff=True):
    return {s["title"]: s for s in build_agent_info(key, d or bundle(), staff)["sections"]}


def rows_of(section):
    return {i["label"]: i["value"] for i in section["items"]}


def test_every_agent_has_a_detail_view():
    for key in AGENT_KEYS:
        info = build_agent_info(key, bundle(), True)
        assert info["key"] == key and info["name"] and info["role"] and info["sections"]


def test_staff_see_each_suppliers_reply_with_a_short_answer_and_the_chosen_one_marked():
    s = sections("vendor")
    assert rows_of(s["Suppliers"])["Replied"] == "2 of 2" and rows_of(s["Suppliers"])["Reminders sent"] == "1"
    replies = s["What each supplier replied"]
    assert replies["highlight"] == 0 and replies["rows"][0][:4] == ["Bhore Shrikrishna", "₹38,000", "5 days", "net 30"]
    assert replies["rows"][1][5].startswith("Total Rs 36000")                      # the short answer, in their words
    assert s["Why Bhore Shrikrishna is selected"]["body"].startswith("Best overall")
    assert "Digv Bhore was cheaper" in s["Note"]["body"]


def test_the_approval_shows_each_rule_and_how_it_came_out():
    s = sections("approval")
    rules = {c["label"]: c for c in s["Rules checked"]["items"]}
    assert all(c["status"] == "pass" for c in rules.values())
    assert "₹38,000" in rules["Order value is within the automatic limit"]["detail"]
    assert rows_of(s["Decision"])["Result"] == "Approved automatically"


def test_an_approval_that_needed_a_person_shows_which_rule_failed_and_why():
    d = bundle(quotes=[{**bundle()["quotes"][0], "price": 90000.0}], approvals=[{
        "status": "pending", "decided_by": None, "decided_at": None, "decision_note": None, "created_at": T,
        "reasons": ["Amount 90,000.00 exceeds the auto-approve limit of 50,000.00."]}])
    s = sections("approval", d)
    rules = {c["label"]: c["status"] for c in s["Rules checked"]["items"]}
    assert rules["Order value is within the automatic limit"] == "fail" and rules["Enough quotes to compare"] == "fail"
    assert "exceeds the auto-approve limit" in s["Why a person was needed"]["body"]
    assert rows_of(s["Decision"])["Result"] == "Waiting for a person to decide"


def test_the_invoice_match_is_shown_rule_by_rule():
    s = sections("invoice")
    rules = {c["label"]: c for c in s["How it was matched"]["items"]}
    assert all(c["status"] == "pass" for c in rules.values()), rules
    assert "Invoice ₹38,000 · order ₹38,000" in rules["Total matches the order"]["detail"]
    assert "Invoice 20 · ordered 20" == rules["Quantity matches the order"]["detail"]
    assert rows_of(s["Invoice INV-1001"])["Result"] == "Matched, cleared for payment"
    assert s["What the supplier sent"]["body"].startswith("Invoice INV-1001")


def test_a_mismatching_invoice_says_what_is_wrong():
    wrong = {**bundle()["invoices"][0], "total_amount": 45000.0, "status": "mismatch",
             "issues": ["Invoice total 45,000.00 differs from the purchase order total 38,000.00."]}
    s = sections("invoice", bundle(invoices=[wrong]))
    rules = {c["label"]: c for c in s["How it was matched"]["items"]}
    assert rules["Total matches the order"]["status"] == "fail" and "₹45,000" in rules["Total matches the order"]["detail"]
    assert "differs from the purchase order total" in s["Problems found"]["body"]


def test_an_invoice_waiting_for_the_goods_shows_that_rule_as_waiting():
    held = {**bundle()["invoices"][0], "status": "on_hold", "issues": ["Waiting for the goods to be confirmed as received."]}
    d = bundle(invoices=[held], delivery={**bundle()["delivery"], "delivery_status": "pending", "delivered_at": None})
    rules = {c["label"]: c["status"] for c in sections("invoice", d)["How it was matched"]["items"]}
    assert rules["Goods confirmed as received"] == "wait"


def test_a_duplicate_invoice_number_fails_that_rule():
    dup = {**bundle()["invoices"][0], "status": "mismatch", "issues": ["Invoice INV-1001 was already submitted by this vendor (possible duplicate)."]}
    rules = {c["label"]: c["status"] for c in sections("invoice", bundle(invoices=[dup]))["How it was matched"]["items"]}
    assert rules["Not a duplicate"] == "fail"


def test_procurement_the_order_and_delivery_carry_their_numbers_for_staff():
    assert sections("procurement")["Item by item"]["rows"][0] == ["ABC fire extinguisher 4kg", "20", "0", "no match in the Store Room", "No"]
    po = rows_of(sections("po")["Order"])
    assert po["Number"] == "PO-1003" and po["Total"] == "₹38,000" and po["Supplier"] == "Bhore Shrikrishna"
    dl = rows_of(sections("delivery")["Delivery"])
    assert dl["Status"] == "Received" and dl["Received by"] == "mgr@x.co" and dl["Note"] == "All 20 checked"


def test_operations_and_notification_report_the_record_and_the_emails():
    ops = sections("operations")
    assert rows_of(ops["The record"])["Steps recorded"] == "12" and "Every move the case made" in ops
    note = sections("notification")
    assert rows_of(note["Emails to people"])["Times someone was told"] == "1"
    assert note["What it did"]["items"][0]["text"].startswith("Emailed 2 approver(s) about approval needed")


def test_a_requester_gets_the_story_without_money_supplier_names_or_internal_reasons():
    everything = str([build_agent_info(k, bundle(), False) for k in AGENT_KEYS])
    for secret in ("Bhore", "Digv", "₹", "38000", "38,000", "36,000", "shri@v.co", "mgr@x.co", "net 30", "INV-1001", "PO-1003",
                   "Best overall", "reliab", "alice@x.co", "policy", "Matched, cleared"):
        assert secret not in everything, secret
    assert rows_of(sections("vendor", staff=False)["Suppliers"])["Replied"] == "2 of 2"
    assert rows_of(sections("po", staff=False)["Order"])["Expected by"] == "2026-10-07"


def test_an_agent_that_has_not_started_simply_has_nothing_to_show():
    empty = {"case": {"requester_id": "a", "stage": "created", "status": "open", "created_at": T}, "events": []}
    for key in ("purchase", "procurement", "vendor", "approval", "po", "delivery", "invoice"):
        assert build_agent_info(key, empty, True)["sections"] == []


# ----------------------------------------------------------------------------------------------- the endpoint

@pytest.fixture
def people(monkeypatch):
    users = {"alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
             "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True)}
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    mine, theirs = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"
    owners = {mine: "alice@x.co", theirs: "bob@x.co"}
    monkeypatch.setattr("app.core.case_access.case_repository.find_case_by_id",
                        lambda cid: SimpleNamespace(requester_id=owners[cid]) if cid in owners else None)
    c, d = agent_flow_controller, bundle()
    monkeypatch.setattr(c.operations_agent, "get_case_status", lambda cid: d["case"])
    monkeypatch.setattr(c.operations_agent, "get_case_events", lambda cid: d["events"])
    monkeypatch.setattr(c.vendor_agent, "get_rfqs", lambda cid: d["rfqs"])
    monkeypatch.setattr(c.vendor_agent, "get_quotes", lambda cid: d["quotes"])
    monkeypatch.setattr(c.vendor_agent, "get_earlier_quotes", lambda cid: [])
    monkeypatch.setattr(c.vendor_agent, "get_vendor_selection", lambda cid: d["selection"])
    monkeypatch.setattr(c.vendor_agent, "get_all_vendors", lambda: list(d["vendors"].values()))
    access.invalidate()
    yield mine, theirs
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_the_detail_needs_a_login():
    assert client.get("/agent-flow/cases/x/agents/vendor").status_code == 401


def test_staff_get_the_full_vendor_detail_over_the_api(people):
    mine, _ = people
    body = client.get(f"/agent-flow/cases/{mine}/agents/vendor", headers=as_("mgr", "manager")).json()
    assert body["audience"] == "staff" and any(s["title"] == "What each supplier replied" for s in body["sections"])


def test_a_requester_gets_their_own_detail_without_supplier_names(people):
    mine, _ = people
    r = client.get(f"/agent-flow/cases/{mine}/agents/vendor", headers=as_("alice", "user"))
    assert r.status_code == 200 and r.json()["audience"] == "requester"
    assert "Bhore" not in r.text and "₹" not in r.text


def test_a_requester_cannot_open_the_detail_of_someone_elses_case(people):
    _, theirs = people
    assert client.get(f"/agent-flow/cases/{theirs}/agents/vendor", headers=as_("alice", "user")).status_code == 404


def test_an_unknown_agent_is_refused(people):
    mine, _ = people
    assert client.get(f"/agent-flow/cases/{mine}/agents/wizard", headers=as_("mgr", "manager")).status_code == 409


def test_the_vendor_detail_shows_the_ai_ranking_with_a_reason_for_each_supplier():
    ranking = sections("vendor")["The AI's ranking, best first"]
    assert ranking["columns"] == ["#", "Supplier", "Price", "Delivery", "Why"]
    assert ranking["rows"][0] == ["1", "Bhore Shrikrishna", "₹38,000", "5 days", "Fast enough and best terms."]
    assert ranking["rows"][1][1:] == ["Digv Bhore", "₹36,000", "7 days", "Cheapest but slowest."]
    assert "The AI's ranking, best first" not in sections("vendor", staff=False)
