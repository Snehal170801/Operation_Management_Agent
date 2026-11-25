"""Printable documents: the purchase order and the one-page approval summary. Staff only; nothing exists to print before the order does."""

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
import io

from app.api import deps
from app.core import documents, pdf_render
from app.main import app
from app.models.auth_schemas import CurrentUser

from .fake_world import World
from .test_restock import ADMIN, STORES, ordered_reorder, w  # noqa: F401 (the fixture)

client = TestClient(app, raise_server_exceptions=False)


def text_of(pdf: bytes) -> tuple[int, str]:
    reader = PdfReader(io.BytesIO(pdf))
    return len(reader.pages), "\n".join(p.extract_text() for p in reader.pages)


# ---- the content rules -----------------------------------------------------------------------------------------------------------

def test_text_is_made_safe_for_the_built_in_font():
    assert documents.safe_text("₹5,000 – “ok” …") == 'Rs 5,000 - "ok" ...'
    assert set(documents.safe_text("शर्मा")) == {"?"}
    assert documents.safe_text(None) == ""


def test_file_names_are_plain():
    assert documents.file_name("PO", "PO-12") == "PO-12.pdf" and documents.file_name("PO", "12") == "PO-12.pdf" and documents.file_name("PO", "po-12") == "po-12.pdf"
    assert documents.file_name("Approval", "REQ-2026-0001") == "Approval-REQ-2026-0001.pdf" and documents.file_name("PO", None) == "PO.pdf"
    assert "/" not in documents.file_name("A", "a/b") and '"' not in documents.file_name("A", 'a"b')


def test_long_text_is_cut_and_extra_offers_are_counted():
    review = {"options": [{"vendor_id": str(i), "vendor_name": f"S{i}", "price": 100.0 + i, "rationale": "x"} for i in range(9)],
              "request_text": "r" * 2000, "rationale": "y" * 5000, "selected_vendor_id": "1", "recommended_vendor_id": "0"}
    doc = documents.approval_summary(review, {"status": "approved", "decided_by": "ravi"}, {"name": "Co"}, None)
    assert len(doc["offers"]) == documents.MAX_OFFERS and doc["offers_left_out"] == 3
    assert len(doc["request_text"]) <= 420 and doc["decision"]["different_from_ai"] is True and doc["decision"]["supplier"] == "S1"


# ---- the pictures ------------------------------------------------------------------------------------------------------------------

def stress_review():
    options = [{"vendor_id": str(i), "vendor_name": "Supplier " + "N" * 60, "price": 1234567.5, "lead_time_days": 9, "reliability": 4.5,
                "terms": "t" * 300, "tags": ["Cheapest", "Fastest", "Preferred supplier"], "reason": "because " * 60, "rank": i + 1} for i in range(10)]
    return {"case_number": "REQ-2026-0001", "requested_by": "ravi", "request_text": "need " * 300, "items": [{"description": "Thing " * 20, "quantity": 5}] * 12,
            "reasons": ["a reason " * 30] * 6, "options": options, "recommended_vendor_id": "0", "selected_vendor_id": "1", "rationale": "why " * 400, "suggestion": "s " * 300}


def test_the_approval_summary_is_always_exactly_one_page_even_for_enormous_content():
    doc = documents.approval_summary(stress_review(), {"status": "approved", "decided_by": "x" * 80, "decision_note": "n " * 400}, {"name": "Co"}, "PO-1")
    pages, text = text_of(pdf_render.render_approval_summary(doc))
    assert pages == 1 and "APPROVAL SUMMARY" in text and "REQ-2026-0001" in text


def test_a_long_purchase_order_runs_onto_more_pages_instead_of_losing_lines():
    po = {"po_number": "PO-7", "vendor_name": "Acme", "total_amount": 1000.0, "items": [{"description": f"Item {i}", "quantity": i + 1} for i in range(60)], "status": "sent"}
    pages, text = text_of(pdf_render.render_purchase_order(documents.purchase_order(po, None, {"name": "Co"}, "REQ-1", "ravi")))
    assert pages >= 2 and "Item 59" in text and "Rs 1,000.00" in text


# ---- end to end through the routes ---------------------------------------------------------------------------------------------

@pytest.fixture
def staff(monkeypatch, w):  # noqa: F811
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: role in ("admin", "u_stores"))
    app.dependency_overrides[deps.get_current_user] = lambda: ADMIN
    yield
    app.dependency_overrides.clear()


def test_a_finished_order_prints_as_both_documents(staff, w):  # noqa: F811
    case_id = ordered_reorder(w)
    po = client.get(f"/cases/{case_id}/documents/purchase-order.pdf")
    assert po.status_code == 200 and po.headers["content-type"] == "application/pdf" and po.headers["cache-control"] == "no-store"
    assert po.headers["content-disposition"].startswith('inline; filename="PO-') and "PO-PO-" not in po.headers["content-disposition"]
    pages, text = text_of(po.content)
    assert pages == 1 and "PURCHASE ORDER" in text and "CCTV camera" in text
    summary = client.get(f"/cases/{case_id}/documents/approval-summary.pdf")
    assert summary.status_code == 200
    pages, text = text_of(summary.content)
    assert pages == 1 and "Approved" in text and "approver" in text and "Acme" in text


def test_before_an_order_exists_there_is_nothing_to_print(staff, w):  # noqa: F811
    case_id = (w.teach("2 laptops please", [{"description": "Laptop", "quantity": 2}]), w.submit("2 laptops please"))[1]
    assert client.get(f"/cases/{case_id}/documents/purchase-order.pdf").status_code == 404
    assert client.get(f"/cases/{case_id}/documents/approval-summary.pdf").status_code == 404
    assert client.get("/cases/00000000-0000-0000-0000-000000000000/documents/purchase-order.pdf").status_code == 404


def test_people_without_view_all_cannot_print_and_signed_out_gets_401(monkeypatch, w):  # noqa: F811
    case_id = ordered_reorder(w)
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: False)
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="req", role="u_requester")
    try:
        assert client.get(f"/cases/{case_id}/documents/purchase-order.pdf").status_code == 403
        assert client.get(f"/cases/{case_id}/documents/approval-summary.pdf").status_code == 403
    finally:
        app.dependency_overrides.clear()
    assert client.get(f"/cases/{case_id}/documents/purchase-order.pdf").status_code == 401
