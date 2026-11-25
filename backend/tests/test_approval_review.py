"""The approver's review: every supplier ranked with a reason, and the person's own choice of supplier."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.controllers import approval_controller
from app.core import access, security
from app.core.approval_review import build_review
from app.core.exceptions import RuleViolation
from app.core.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from app.core.vendor_ranking import normalize_ranking
from app.main import app
from app.repositories import role_repository, user_repository

T = datetime(2026, 10, 2, 12, 0)
client = TestClient(app)
CASE = "aaaaaaaa-0000-4000-8000-000000000001"


def quote(vid, name, price, days, terms, text=None):
    return {"vendor_id": vid, "vendor_name": name, "price": price, "lead_time_days": days, "terms": terms,
            "raw_quote_text": text or f"Total Rs {price} Delivery {days} days terms {terms}"}


QUOTES = [quote("v1", "Acme", 95000.0, 5, "net 30"), quote("v2", "Globex", 98500.0, 3, "50% advance"), quote("v3", "Initech", 92000.0, 7, "net 15")]


# ------------------------------------------------------------------------------------- tidying the AI's ranking

def test_a_good_ranking_is_kept_in_order_with_its_reasons():
    ranking, why = normalize_ranking({"ranking": [{"vendor_id": "v2", "reason": "Fastest"}, {"vendor_id": "v1", "reason": "Balanced"},
                                                  {"vendor_id": "v3", "reason": "Cheapest, slow"}], "rationale": "Globex wins on speed."}, QUOTES)
    assert [(r["rank"], r["vendor_id"], r["reason"]) for r in ranking] == [(1, "v2", "Fastest"), (2, "v1", "Balanced"), (3, "v3", "Cheapest, slow")]
    assert why == "Globex wins on speed."


def test_unknown_repeated_and_forgotten_suppliers_are_sorted_out():
    ranking, _ = normalize_ranking({"ranking": [{"vendor_id": "ghost", "reason": "x"}, {"vendor_id": "v1", "reason": "ok"},
                                                {"vendor_id": "v1", "reason": "again"}]}, QUOTES)
    assert [r["vendor_id"] for r in ranking] == ["v1", "v3", "v2"]          # the forgotten two follow, cheapest first
    assert ranking[1]["reason"] == "The AI did not rank this supplier." and ranking[0]["reason"] == "ok"


def test_the_old_single_pick_answer_still_works():
    ranking, why = normalize_ranking({"recommended_vendor_id": "v3", "rationale": "Cheapest."}, QUOTES)
    assert ranking[0] == {"vendor_id": "v3", "rank": 1, "reason": "Cheapest."} and len(ranking) == 3 and why == "Cheapest."


def test_garbage_from_the_ai_still_gives_every_supplier_a_place():
    ranking, _ = normalize_ranking({"ranking": "nonsense", "recommended_vendor_id": 12}, QUOTES)
    assert sorted(r["vendor_id"] for r in ranking) == ["v1", "v2", "v3"] and [r["rank"] for r in ranking] == [1, 2, 3]


def test_a_supplier_with_no_price_is_ranked_last_when_the_ai_forgets_it():
    ranking, _ = normalize_ranking({}, QUOTES + [quote("v4", "NoPrice", None, None, None)])
    assert ranking[-1]["vendor_id"] == "v4"


# ------------------------------------------------------------------------------------- what the approver sees

APPROVAL = {"approval_id": "ap1", "case_id": CASE, "status": "pending", "reasons": ["Amount 95,000.00 exceeds the auto-approve limit of 50,000.00."]}
VENDORS = {"v1": {"email": "a@v.co", "reliability_score": 4.2}, "v2": {"email": "g@v.co", "reliability_score": 4.0}, "v3": {"email": "i@v.co", "reliability_score": 3.5}}
EVENTS = [{"event_id": 1, "event_type": "vendor.selected", "payload": {"ranking": [
    {"vendor_id": "v1", "rank": 1, "reason": "Balanced price and delivery."}, {"vendor_id": "v2", "rank": 2, "reason": "Fastest but dearest."},
    {"vendor_id": "v3", "rank": 3, "reason": "Cheapest but slowest."}]}, "created_at": T}]


def review(**over):
    d = dict(approval=APPROVAL, case={"case_number": "REQ-2026-0002", "requester_id": "alice@x.co"},
             request={"raw_request": "Need 60 extinguishers", "items": [{"description": "ABC 4kg", "quantity": 60}]},
             quotes=QUOTES, vendors=VENDORS, selection={"vendor_id": "v1", "rationale": "Balanced."}, events=EVENTS)
    d.update(over)
    return build_review(**d)


def test_the_review_lists_every_supplier_in_the_ais_order_with_all_the_details():
    r = review()
    assert [o["vendor_name"] for o in r["options"]] == ["Acme", "Globex", "Initech"] and [o["rank"] for o in r["options"]] == [1, 2, 3]
    first = r["options"][0]
    assert first["price"] == 95000.0 and first["lead_time_days"] == 5 and first["terms"] == "net 30" and first["reliability"] == 4.2
    assert first["reply_text"] == "Total Rs 95000.0 Delivery 5 days terms net 30" and first["reason"] == "Balanced price and delivery."
    assert r["reasons"] == APPROVAL["reasons"] and r["request_text"] == "Need 60 extinguishers" and r["requested_by"] == "alice@x.co"


def test_the_cheapest_and_fastest_are_marked_and_the_ai_pick_is_flagged():
    tags = {o["vendor_name"]: o["tags"] for o in review()["options"]}
    assert tags == {"Acme": ["AI's pick"], "Globex": ["Fastest"], "Initech": ["Cheapest"]}
    assert review()["recommended_vendor_id"] == "v1" and review()["selected_vendor_id"] == "v1"


def test_with_no_ranking_on_record_the_suppliers_are_shown_cheapest_first_without_reasons():
    r = review(events=[])
    assert [o["vendor_name"] for o in r["options"]] == ["Initech", "Acme", "Globex"] and all(o["reason"] is None for o in r["options"])


def test_a_person_choosing_someone_else_shows_who_is_selected_now_but_keeps_the_ais_pick():
    r = review(selection={"vendor_id": "v3", "rationale": "Chosen by mgr instead of Acme."})
    assert r["selected_vendor_id"] == "v3" and r["recommended_vendor_id"] == "v1" and "AI's pick" in r["options"][0]["tags"]


def test_only_a_suppliers_best_quote_is_shown_when_it_quoted_twice():
    r = review(quotes=QUOTES + [quote("v1", "Acme", 90000.0, 5, "net 30")])
    assert len(r["options"]) == 3 and r["options"][0]["price"] == 90000.0


# ------------------------------------------------------------------------------------- choosing the supplier when approving

@pytest.fixture
def staff(monkeypatch):
    users = {"apr": SimpleNamespace(user_id="apr", username="apr@x.co", role="dept_approval", is_active=True),
             "viewer": SimpleNamespace(user_id="viewer", username="v@x.co", role="viewer", is_active=True)}
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "dept_approval": {"approvals:read", "approvals:write", "cases:read", "cases:read_all"}, "viewer": set(DEFAULT_ROLE_PERMISSIONS["viewer"]),
        "admin": set(ALL_PERMISSIONS)})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    audited, picked, decided = [], [], []
    c = approval_controller
    monkeypatch.setattr(c.audit, "record", lambda action, **kw: audited.append((action, kw)))
    monkeypatch.setattr(c.approval_agent, "get_approval", lambda aid: {**APPROVAL, "status": "pending", "case_number": "REQ-2026-0002",
                                                                       "approval_type": "vendor_selection", "decided_by": None, "decision_note": None,
                                                                       "created_at": T, "decided_at": None})
    monkeypatch.setattr(c.operations_agent, "get_case_status", lambda cid: {"requester_id": "alice@x.co", "case_number": "REQ-2026-0002"})
    monkeypatch.setattr(c.vendor_agent, "choose_vendor", lambda case_id, vid, by, note: picked.append((vid, by, note)) or {"from": "Acme", "to": "Initech"})
    monkeypatch.setattr(c.case_pipeline, "decide_approval", lambda aid, approve, by, note: decided.append((approve, by)) or {
        **APPROVAL, "status": "approved" if approve else "rejected", "case_number": "REQ-2026-0002", "approval_type": "vendor_selection",
        "decided_by": by, "decision_note": note, "created_at": T, "decided_at": T})
    access.invalidate()
    yield audited, picked, decided
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_the_approver_picks_a_different_supplier_and_it_is_applied_before_the_order_goes_out(staff):
    audited, picked, decided = staff
    r = client.post("/approvals/ap1/approve", headers=as_("apr", "dept_approval"), json={"vendor_id": "v3", "note": "Need it cheap"})
    assert r.status_code == 200 and picked == [("v3", "apr@x.co", "Need it cheap")] and decided == [(True, "apr@x.co")]
    assert audited[0][1]["detail"]["supplier_changed_from"] == "Acme" and audited[0][1]["detail"]["supplier_changed_to"] == "Initech"


def test_approving_without_naming_a_supplier_goes_with_the_current_one(staff):
    audited, picked, decided = staff
    assert client.post("/approvals/ap1/approve", headers=as_("apr", "dept_approval"), json={}).status_code == 200
    assert picked == [] and decided == [(True, "apr@x.co")] and "supplier_changed_to" not in audited[0][1]["detail"]


def test_rejecting_never_changes_the_supplier(staff):
    audited, picked, decided = staff
    assert client.post("/approvals/ap1/reject", headers=as_("apr", "dept_approval"), json={"vendor_id": "v3"}).status_code == 200
    assert picked == [] and decided == [(False, "apr@x.co")]


def test_a_decision_already_made_cannot_be_used_to_change_the_supplier(staff, monkeypatch):
    audited, picked, decided = staff
    monkeypatch.setattr(approval_controller.approval_agent, "get_approval", lambda aid: {**APPROVAL, "status": "approved"})
    r = client.post("/approvals/ap1/approve", headers=as_("apr", "dept_approval"), json={"vendor_id": "v3"})
    assert r.status_code == 409 and picked == [] and decided == []


def test_a_supplier_that_never_quoted_cannot_be_chosen(staff, monkeypatch):
    def refuse(*a):
        raise RuleViolation("That supplier has not sent a priced quote for this request, so it can't be chosen.")
    monkeypatch.setattr(approval_controller.vendor_agent, "choose_vendor", refuse)
    r = client.post("/approvals/ap1/approve", headers=as_("apr", "dept_approval"), json={"vendor_id": "ghost"})
    assert r.status_code == 409 and "priced quote" in r.json()["detail"] and staff[2] == []


def test_the_review_endpoint_returns_the_full_picture_to_approvers(staff, monkeypatch):
    c = approval_controller
    monkeypatch.setattr(c.purchase_agent, "get_purchase_request", lambda cid: {"raw_request": "Need 60", "items": [{"description": "ABC", "quantity": 60}]})
    monkeypatch.setattr(c.vendor_agent, "get_vendor_selection", lambda cid: {"vendor_id": "v1", "rationale": "Balanced."})
    monkeypatch.setattr(c.vendor_agent, "get_quotes", lambda cid: QUOTES)
    monkeypatch.setattr(c.vendor_agent, "get_all_vendors", lambda: [{"vendor_id": k, **v} for k, v in VENDORS.items()])
    monkeypatch.setattr(c.operations_agent, "get_case_events", lambda cid: EVENTS)
    body = client.get("/approvals/ap1/review", headers=as_("apr", "dept_approval")).json()
    assert [o["vendor_name"] for o in body["options"]] == ["Acme", "Globex", "Initech"] and body["options"][0]["reason"] == "Balanced price and delivery."
    assert client.get("/approvals/ap1/review").status_code == 401
