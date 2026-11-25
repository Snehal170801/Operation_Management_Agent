"""The document store: every PO, invoice, quote and received file in one searchable list; staff see all, a requester only a sanitised view of their own cases."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core import document_index as di
from app.main import app
from app.models.auth_schemas import CurrentUser
from app.orchestrator import case_pipeline

from .fake_world import standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

client = TestClient(app, raise_server_exceptions=False)
T = datetime(2026, 10, 9, 10, 0)


# ---- the index (pure) ---------------------------------------------------------------------------------------------------------------------

CASES = {"c1": {"case_number": "REQ-2026-0001"}, "c2": {"case_number": "REQ-2026-0002"}}
POS = [{"purchase_order_id": "p1", "case_id": "c1", "po_number": "PO-1001", "vendor_name": "Acme Supplies", "total_amount": 40000.0, "total_with_tax": 47200.0, "status": "sent", "created_at": T}]
INVS = [{"invoice_id": "i1", "case_id": "c1", "invoice_number": "INV-9", "vendor_name": "Acme Supplies", "total_amount": 47200.0, "status": "matched", "created_at": datetime(2026, 10, 10)},
        {"invoice_id": "i2", "case_id": "c2", "invoice_number": None, "vendor_name": "Globex", "total_amount": None, "status": "on_hold", "created_at": datetime(2026, 10, 8)}]
QUOTES = [{"quote_id": "q1", "case_id": "c1", "vendor_name": "Globex", "price": 45000.0, "created_at": datetime(2026, 10, 7)}]
FILES = [{"case_id": "c1", "file_hash": "a" * 64, "file_name": "quote-acme.pdf", "first_read_at": datetime(2026, 10, 7, 9)}]


def index():
    return di.build(CASES, POS, INVS, QUOTES, FILES)


def test_every_document_appears_newest_first_with_a_readable_title():
    items = index()
    assert [i["kind"] for i in items] == ["invoice", "purchase_order", "invoice", "file", "quote"] and items[0]["at"] > items[-1]["at"]
    titles = {i["id"].split(":")[0] + ":" + i["title"] for i in items}
    assert {"purchase_order:PO-1001", "invoice:Invoice INV-9", "invoice:Invoice (number unreadable)", "quote:Quote from Globex", "file:quote-acme.pdf"} <= titles
    po = next(i for i in items if i["kind"] == "purchase_order")
    assert po["amount"] == 47200.0 and po["case_number"] == "REQ-2026-0001"                   # the cost WITH tax when the order has it


def test_a_row_for_an_unknown_case_still_appears_without_a_number_and_a_missing_date_sorts_last():
    items = di.build({}, POS, [], [], [{"case_id": "zz", "file_hash": "b" * 64, "file_name": None, "first_read_at": None}])
    assert items[0]["case_number"] is None and items[-1]["title"] == "(unnamed file)" and items[-1]["at"] is None


def test_search_needs_every_word_and_looks_at_title_case_supplier_status_and_amount():
    items = index()
    assert di.search(items, "acme", None)["total"] == 3                                      # the PO, its invoice and the file that has "acme" in its name
    assert [i["title"] for i in di.search(items, "acme invoice", None)["items"]] == ["Invoice INV-9"]
    assert di.search(items, "REQ-2026-0002", None)["total"] == 1 and di.search(items, "on hold", None)["total"] == 1
    assert di.search(items, "47,200", None)["total"] == 2 and di.search(items, "47200", None)["total"] == 2
    assert di.search(items, "nothing like this", None)["total"] == 0 and di.search(items, "  ", None)["total"] == 5


def test_the_kind_filter_narrows_the_page_but_the_counts_stay_for_the_tabs_and_an_unknown_kind_matches_nothing():
    page = di.search(index(), "acme", "invoice")
    assert page["total"] == 1 and page["counts"] == {"purchase_order": 1, "invoice": 1, "quote": 0, "file": 1}
    assert di.search(index(), None, "banana")["total"] == 0


def test_paging_is_clamped_and_walks_the_list():
    big = di.build({}, [{"purchase_order_id": str(n), "case_id": "c", "po_number": f"PO-{n}", "vendor_name": "A", "total_amount": 1.0, "status": "sent", "created_at": datetime(2026, 1, 1, 0, n % 60)} for n in range(250)], [], [], [])
    assert len(di.search(big, None, None, limit=500)["items"]) == di.MAX_LIMIT and di.search(big, None, None, limit=0)["limit"] == 1
    assert [len(di.search(big, None, None, limit=100, offset=o)["items"]) for o in (0, 100, 200, 300)] == [100, 100, 50, 0] and di.search(big, None, None, offset=-5)["offset"] == 0


def test_a_requester_sees_only_orders_and_invoices_of_their_own_cases_and_only_that_they_exist():
    mine = di.for_requester(index(), {"C1"})
    assert [i["kind"] for i in mine] == ["invoice", "purchase_order"] and all(i["case_id"] == "c1" for i in mine)
    assert all(i["vendor"] is None and i["amount"] is None and i["status"] is None for i in mine)
    assert {i["title"] for i in mine} == {"Invoice for REQ-2026-0001", "Purchase order for REQ-2026-0001"}
    assert di.for_requester(index(), set()) == []


# ---- the routes ---------------------------------------------------------------------------------------------------------------------------

STAFF = CurrentUser(user_id="1", username="boss", role="admin")
RAVI = CurrentUser(user_id="2", username="ravi@x.co", role="u_requester")


@pytest.fixture
def world(monkeypatch):
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    w = standard_world(monkeypatch)
    ravi_case = w.submit("50 cameras", requester="ravi@x.co")
    source(w, ravi_case, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    case_pipeline.confirm_delivery(ravi_case, "recv", None)
    w.reply(ravi_case, "Acme", "Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.", attachments=[{"name": "invoice-scan.pdf", "text": "(the same invoice as a file)"}],
            subject=f"RE: [OA-{ravi_case}] Purchase Order PO-1001")
    w.teach("2 laptops please", [{"description": "Laptop", "quantity": 2}])
    other_case = w.submit("50 cameras", requester="other@x.co")
    source(w, other_case, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    w.ravi_case, w.other_case = ravi_case, other_case
    return w


def as_user(monkeypatch, user, perms):
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: permission in perms)
    app.dependency_overrides[deps.get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.clear()


def test_staff_search_finds_every_kind_with_suppliers_and_amounts(world, monkeypatch):
    as_user(monkeypatch, STAFF, {"cases:read", "cases:read_all"})
    page = client.get("/document-store?limit=100").json()
    kinds = {i["kind"] for i in page["items"]}
    assert kinds == {"purchase_order", "invoice", "quote", "file"} and page["sanitised"] is False
    assert any(i["kind"] == "file" and i["title"] == "invoice-scan.pdf" for i in page["items"])
    assert any(i["kind"] == "purchase_order" and i["vendor"] == "Acme" and i["amount"] == 42000.0 for i in page["items"])
    assert client.get("/document-store?q=INV-7").json()["total"] >= 1 and client.get("/document-store?q=zzzz").json()["total"] == 0
    assert client.get("/document-store?kind=quote").json()["total"] == len([i for i in page["items"] if i["kind"] == "quote"])


def test_a_requester_gets_only_a_sanitised_view_of_their_own_cases(world, monkeypatch):
    as_user(monkeypatch, RAVI, {"cases:read", "cases:create"})
    page = client.get("/document-store?limit=100").json()
    assert page["sanitised"] is True and page["total"] >= 2
    assert {i["kind"] for i in page["items"]} <= {"purchase_order", "invoice"} and all(i["case_id"].lower() == world.ravi_case.lower() for i in page["items"])
    text = client.get("/document-store?limit=100").text
    for secret in ("Acme", "Globex", "42000", "42,000", "invoice-scan.pdf", "INV-7", "Quote from"):
        assert secret not in text, secret
    assert client.get("/document-store?q=Acme").json()["total"] == 0                       # searching by a supplier finds nothing for them either


def test_one_cases_documents_and_a_stranger_gets_not_found(world, monkeypatch):
    as_user(monkeypatch, STAFF, {"cases:read", "cases:read_all"})
    mine = client.get(f"/cases/{world.ravi_case}/document-store").json()
    assert mine["total"] >= 4 and all(i["case_id"].lower() == world.ravi_case.lower() for i in mine["items"])
    as_user(monkeypatch, RAVI, {"cases:read", "cases:create"})
    assert client.get(f"/cases/{world.ravi_case}/document-store").json()["sanitised"] is True
    assert client.get(f"/cases/{world.other_case}/document-store").status_code == 404      # not their case: "not found", never "forbidden"


def test_nobody_without_the_right_or_signed_out_gets_anything(world, monkeypatch):
    as_user(monkeypatch, CurrentUser(user_id="9", username="nobody", role="u_none"), set())
    assert client.get("/document-store").status_code == 403 and client.get(f"/cases/{world.ravi_case}/document-store").status_code == 403
    app.dependency_overrides.clear()
    assert client.get("/document-store").status_code == 401 and client.get(f"/cases/{world.ravi_case}/document-store").status_code == 401


def test_bad_paging_and_overlong_searches_are_refused(world, monkeypatch):
    as_user(monkeypatch, STAFF, {"cases:read", "cases:read_all"})
    assert client.get("/document-store?limit=0").status_code == 422 and client.get("/document-store?limit=1000").status_code == 422
    assert client.get("/document-store?offset=-1").status_code == 422 and client.get("/document-store?q=" + "x" * 101).status_code == 422
    assert client.get("/document-store?limit=100&offset=100000").json()["items"] == []


def test_the_marker_the_duplicate_email_check_keeps_is_not_listed_as_a_file(world, monkeypatch):
    as_user(monkeypatch, STAFF, {"cases:read", "cases:read_all"})
    from app.agents import document_agent
    document_agent.remember_files(world.ravi_case, [("c" * 64, "(email text)")])                  # what the same-email check keeps: a fingerprint, not a document
    assert ("c" * 64) in world.read_files[world.ravi_case]
    names = [i["title"] for i in client.get("/document-store?kind=file&limit=100").json()["items"]]
    assert "(email text)" not in names and "invoice-scan.pdf" in names
