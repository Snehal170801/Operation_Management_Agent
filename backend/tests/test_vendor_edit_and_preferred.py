"""Editing a supplier's details, and preferred suppliers: marked per stock item, always asked first, a warning when they cannot be asked,
and every existing rule about who gets a quote request stays exactly as it was."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents import approval_agent, vendor_agent
from app.api import deps
from app.controllers import vendor_controller
from app.core import preferred
from app.core.exceptions import InvalidInput, VendorNotFound
from app.main import app
from app.models.auth_schemas import CurrentUser
from app.models.vendor_schemas import UpdateVendorRequest
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_restock import ADMIN, STORES

# ---- the preferred-supplier rule (pure) ----------------------------------------------------------------------------------------------

V = [{"vendor_id": "A", "name": "Acme", "email": "a@x.co"}, {"vendor_id": "B", "name": "Bolt", "email": None},
     {"vendor_id": "C", "name": "Crate", "email": "c@x.co", "email_bounced_at": "2026-10-01"}, {"vendor_id": "D", "name": "Dome", "email": "d@x.co"}]


def test_preferred_suppliers_come_first_and_nobody_is_added_or_dropped():
    ordered = preferred.order_for_asking(V, ["d"])                      # ids are compared without regard to capitals
    assert [v["name"] for v in ordered] == ["Dome", "Acme", "Bolt", "Crate"]
    assert sorted(v["name"] for v in ordered) == sorted(v["name"] for v in V)
    assert preferred.order_for_asking(V, None) == V and preferred.order_for_asking(V, []) == V


def test_a_preferred_supplier_who_cannot_be_asked_is_named():
    assert preferred.unreachable_preferred(V, ["B", "C", "A"]) == ["Bolt", "Crate"]          # no address; an address that bounces
    assert preferred.unreachable_preferred(V, ["A", "D"]) == [] and preferred.unreachable_preferred(V, None) == []


def test_a_supplier_a_person_just_turned_down_is_not_a_warning_because_that_was_a_decision():
    assert preferred.unreachable_preferred(V, ["B"], skip_vendor_id="b") == []


# ---- editing a supplier ----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch) -> World:
    w = standard_world(monkeypatch)
    from app.repositories import audit_repository
    w.audit = []
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: w.audit.append(a))
    return w


def details(w, supplier, **over):
    v = next(x for x in w.vendors.values() if x.name == supplier)
    base = dict(name=v.name, reliability_score=float(v.reliability_score), email=v.email, phone=getattr(v, "phone", None), call_language=getattr(v, "call_language", "hi") or "hi")
    return UpdateVendorRequest(**{**base, **over}), v.vendor_id


def edit(w, supplier, **over):
    request, vid = details(w, supplier, **over)
    vendor_controller.update_vendor(vid, request, STORES)
    return next(v for v in w.vendors.values() if v.vendor_id == vid)


def test_a_supplier_can_be_renamed_and_have_every_detail_changed(w):
    v = edit(w, "Acme", name="  Acme Supplies Ltd ", email="orders@acme.example", phone="+919876543210", call_language="mr", reliability_score=3.5)
    assert (v.name, v.email, v.phone, v.call_language, v.reliability_score) == ("Acme Supplies Ltd", "orders@acme.example", "+919876543210", "mr", 3.5)


def test_clearing_the_email_or_phone_is_allowed(w):
    v = edit(w, "Globex", email=None, phone=None)
    assert v.email is None and v.phone is None


def test_a_name_another_supplier_has_is_refused_in_any_capitals(w):
    with pytest.raises(InvalidInput, match="already a supplier called 'Globex'"):
        edit(w, "Acme", name="GLOBEX")
    assert any(v.name == "Acme" for v in w.vendors.values())


def test_an_email_another_supplier_uses_is_refused_because_replies_could_not_be_told_apart(w):
    with pytest.raises(InvalidInput, match="Globex already uses that e-mail"):
        edit(w, "Acme", email="GLOBEX@vendor.com")


def test_keeping_its_own_name_and_email_is_not_a_clash(w):
    v = edit(w, "Acme", reliability_score=2.0)
    assert v.name == "Acme" and v.email == "acme@vendor.com" and v.reliability_score == 2.0


def test_a_supplier_who_does_not_exist_is_a_404_error(w):
    request, _ = details(w, "Acme")
    with pytest.raises(VendorNotFound):
        vendor_controller.update_vendor("00000000-0000-0000-0000-000000000000", request, STORES)


def test_a_new_email_address_clears_the_bounced_flag_but_the_same_one_does_not(w):
    vid = w.vendor_id("Acme")
    vendor_agent.mark_email_bounced(vid, "mailbox full")
    assert w.vendors[vid].email_bounced_at is not None
    edit(w, "Acme", reliability_score=4.0)                                         # same address: still known not to work
    assert w.vendors[vid].email_bounced_at is not None
    edit(w, "Acme", email="new@acme.example")                                      # a different address deserves a chance
    assert w.vendors[vid].email_bounced_at is None and w.vendors[vid].email_bounce_reason is None


@pytest.mark.parametrize("field,value", [("email", "not-an-address"), ("email", "a b@c.d"), ("phone", "9876543210"), ("phone", "+12"),
                                          ("reliability_score", 5.5), ("reliability_score", -1), ("call_language", "fr"), ("name", "")])
def test_details_that_cannot_be_right_are_refused_before_anything_is_saved(w, field, value):
    with pytest.raises(ValidationError):
        details(w, "Acme", **{field: value})


def test_the_audit_log_records_only_what_changed(w):
    edit(w, "Acme", reliability_score=2.0, phone="+919876543210")
    entry = [a for a in w.audit if a[2] == "vendor.update"][0]
    detail = str(entry[-2])
    assert entry[1] == "stores" and "reliability_score" in detail and "phone" in detail and "email" not in detail and "call_language" not in detail


client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def signed_in(monkeypatch, w):
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: role in ("admin", "u_vendor") or permission == "vendors:read")
    app.dependency_overrides[deps.get_current_user] = lambda: ADMIN
    yield
    app.dependency_overrides.clear()


def body(w, supplier, **over):
    request, vid = details(w, supplier, **over)
    return vid, request.model_dump()


def test_the_edit_route_saves_and_answers_clearly_when_it_cannot(signed_in, w):
    vid, payload = body(w, "Acme", reliability_score=2.5)
    assert client.put(f"/vendors/{vid}", json=payload).status_code == 204 and w.vendors[vid].reliability_score == 2.5
    vid, payload = body(w, "Acme", name="Globex")
    clash = client.put(f"/vendors/{vid}", json=payload)
    assert clash.status_code == 422 and "already a supplier called" in clash.json()["detail"]
    assert client.put("/vendors/00000000-0000-0000-0000-000000000000", json=payload).status_code == 404
    assert client.put(f"/vendors/{vid}", json={**payload, "email": "nope"}).status_code == 422


def test_someone_who_may_only_read_suppliers_cannot_edit_one(monkeypatch, w):
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: permission == "vendors:read")
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="viewer", role="u_view")
    try:
        vid, payload = body(w, "Acme", reliability_score=1.0)
        assert client.put(f"/vendors/{vid}", json=payload).status_code == 403 and w.vendors[vid].reliability_score == 4.5
    finally:
        app.dependency_overrides.clear()


def test_nobody_signed_out_can_edit_a_supplier(w):
    app.dependency_overrides.clear()
    assert client.put(f"/vendors/{w.vendor_id('Acme')}", json={"name": "X", "reliability_score": 3}).status_code == 401


# ---- preferred suppliers in the flow ---------------------------------------------------------------------------------------------------

def rfqs(w, mark=0):
    return [m[0] for m in w.sent[mark:] if "Request for quotation" in m[1]]


def prefer(w, name):
    w.stock["cctv camera"].preferred_vendor_id = w.vendor_id(name)


def test_the_preferred_supplier_is_asked_first_and_every_other_rule_is_unchanged(w):
    prefer(w, "Initech")                                                          # alphabetically last
    w.submit("50 cameras")
    assert rfqs(w) == ["initech@vendor.com", "acme@vendor.com", "globex@vendor.com"]               # first, then everyone else as before


def test_with_no_preferred_supplier_nothing_changes(w):
    case_id = w.submit("50 cameras")
    assert sorted(rfqs(w)) == ["acme@vendor.com", "globex@vendor.com", "initech@vendor.com"]
    assert not [e for e in w.events[case_id] if e.event_type == "rfq.preferred_unreachable"]


def test_a_preferred_supplier_with_no_email_is_flagged_and_the_request_still_goes_to_the_others(w):
    w.vendors[w.vendor_id("Initech")].email = None
    prefer(w, "Initech")
    case_id = w.submit("50 cameras")
    assert sorted(rfqs(w)) == ["acme@vendor.com", "globex@vendor.com"] and w.stage(case_id) == "awaiting_quotes"      # existing rule: skipped, not stalled
    flagged = [e for e in w.events[case_id] if e.event_type == "rfq.preferred_unreachable"]
    assert flagged and flagged[0].payload["vendors"] == ["Initech"]


def test_a_preferred_supplier_whose_email_bounces_is_flagged_too(w):
    vendor_agent.mark_email_bounced(w.vendor_id("Acme"), "no such mailbox")
    prefer(w, "Acme")
    case_id = w.submit("50 cameras")
    assert "acme@vendor.com" not in rfqs(w)
    assert [e for e in w.events[case_id] if e.event_type == "rfq.preferred_unreachable"][0].payload["vendors"] == ["Acme"]


def test_a_request_for_other_items_does_not_involve_the_preferred_supplier_marked_for_something_else(w):
    prefer(w, "Initech")                                                          # marked for CCTV cameras only
    w.stock["laptop"].quantity_available = 0                                      # so a laptop request goes out for quotes
    w.submit("10 laptops")
    assert rfqs(w) == ["acme@vendor.com", "globex@vendor.com", "initech@vendor.com"]               # plain order, nobody moved


def test_two_items_with_different_preferred_suppliers_ask_both_first(w):
    w.stock["laptop"].preferred_vendor_id = w.vendor_id("Globex")
    prefer(w, "Initech")
    w.teach("5 laptops and 2 cameras", [{"description": "Laptop", "quantity": 5}, {"description": "CCTV camera", "quantity": 2}])
    w.stock["cctv camera"].quantity_available = 0
    w.stock["laptop"].quantity_available = 0
    w.submit("5 laptops and 2 cameras")
    assert rfqs(w)[:2] == ["globex@vendor.com", "initech@vendor.com"] and len(rfqs(w)) == 3


def test_a_problem_looking_up_preferred_suppliers_never_stops_the_quotes_going_out(w, monkeypatch):
    prefer(w, "Initech")

    def boom(items):
        raise RuntimeError("database down")

    monkeypatch.setattr(case_pipeline.procurement_agent, "preferred_vendor_ids", boom)
    case_id = w.submit("50 cameras")
    assert sorted(rfqs(w)) == ["acme@vendor.com", "globex@vendor.com", "initech@vendor.com"] and w.stage(case_id) == "awaiting_quotes"


def over_the_limit(w):
    """A request whose offers are all above the automatic limit, so it waits for a person. Returns (case id, its pending approval)."""
    w.teach("8 steel racks", [{"description": "Steel rack", "quantity": 8}])
    w.add_stock("Steel rack", 0)
    case = w.submit("8 steel racks")
    for name, price in (("Acme", 72000), ("Globex", 74000), ("Initech", 76000)):
        w.reply(case, name, f"Hello, 8 steel racks total Rs {price}, delivery 5 days, payment 30 days.")
    return case, next(a for a in approval_agent.get_approvals(case_id=case) if a["status"] == "pending")


def test_asking_again_after_a_rejection_keeps_the_preferred_supplier_first_and_still_asks_everyone(w):
    case, approval = over_the_limit(w)
    w.stock["steel rack"].preferred_vendor_id = w.vendor_id("Initech")
    mark = len(w.sent)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", "too dear", re_source=True)
    asked = rfqs(w, mark)
    assert asked == ["initech@vendor.com", "acme@vendor.com", "globex@vendor.com"]


def test_a_supplier_the_approver_turned_down_is_not_asked_again_even_if_preferred_and_it_is_not_a_warning(w):
    case, approval = over_the_limit(w)
    chosen = vendor_agent.get_vendor_selection(case)["vendor_name"]                 # whoever the system picked
    w.stock["steel rack"].preferred_vendor_id = w.vendor_id(chosen)                 # ... is also the preferred one
    mark = len(w.sent)
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", None, re_source=True, skip_selected=True)
    asked = rfqs(w, mark)
    assert f"{chosen.lower()}@vendor.com" not in asked and len(asked) == 2           # a decision beats "always"
    assert not [e for e in w.events[case] if e.event_type == "rfq.preferred_unreachable"]


def test_asking_again_warns_when_a_preferred_supplier_cannot_be_asked(w):
    case, approval = over_the_limit(w)
    w.stock["steel rack"].preferred_vendor_id = w.vendor_id("Initech")
    w.vendors[w.vendor_id("Initech")].email = None
    case_pipeline.decide_approval(approval["approval_id"], False, "mgr", None, re_source=True)
    flagged = [e for e in w.events[case] if e.event_type == "rfq.preferred_unreachable"]
    assert flagged and flagged[-1].payload["vendors"] == ["Initech"]


def test_the_approver_sees_which_offer_is_from_the_preferred_supplier(w):
    case, approval = over_the_limit(w)
    w.stock["steel rack"].preferred_vendor_id = w.vendor_id("Globex")
    review = case_pipeline.approval_review(approval["approval_id"])
    tags = {o["vendor_name"]: o["tags"] for o in review["options"]}
    assert "Preferred supplier" in tags["Globex"] and "Preferred supplier" not in tags["Acme"] and "Preferred supplier" not in tags["Initech"]


def test_the_warning_has_a_label_people_can_read():
    from app.core.agent_flow import _DOMAIN_FEED as EVENT_INFO
    assert "rfq.preferred_unreachable" in EVENT_INFO
