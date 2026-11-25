"""CSV exports of cases, purchase orders, invoices and stock: the right rows, spreadsheet-safe cells, and server-side permissions
(a requester gets only their own cases and nothing else)."""

import csv
import io
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core import exports
from app.main import app
from app.models.auth_schemas import CurrentUser

from .fake_world import World
from .test_restock import ADMIN, ordered_reorder, w  # noqa: F401 (the fixture)

client = TestClient(app, raise_server_exceptions=False)
STAFF = {"admin", "u_stores"}


def parse(response) -> list[list[str]]:
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


# ---- the cells ----------------------------------------------------------------------------------------------------------------------------

def test_text_that_a_spreadsheet_would_run_as_a_formula_is_defused_and_other_values_are_plain():
    for evil in ('=HYPERLINK("http://x","click")', "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"):
        assert exports.safe_cell(evil) == "'" + evil
    assert exports.safe_cell("Acme") == "Acme" and exports.safe_cell(None) == "" and exports.safe_cell(-5) == -5 and exports.safe_cell(1.5) == 1.5
    assert exports.safe_cell(True) == "Yes" and exports.safe_cell(datetime(2026, 10, 7, 9, 5)) == "2026-10-07 09:05" and exports.safe_cell(date(2026, 10, 7)) == "2026-10-07"


def test_the_file_has_a_header_a_byte_order_mark_and_commas_and_quotes_survive():
    data = exports.to_csv("stock", [['Cable, "red"', 5, "pcs", None, None, None, False, None, None]])
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert data.startswith(b"\xef\xbb\xbf") and rows[0][0] == "Item" and rows[1][0] == 'Cable, "red"' and len(rows[1]) == len(rows[0])


def test_file_names_say_what_and_when():
    assert exports.file_name("purchase-orders", date(2026, 10, 7)) == "purchase-orders-2026-10-07.csv"


# ---- the routes ---------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def staff(monkeypatch, w):  # noqa: F811
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: role in STAFF)
    app.dependency_overrides[deps.get_current_user] = lambda: ADMIN
    yield
    app.dependency_overrides.clear()


def test_staff_get_all_four_exports_with_the_right_rows(staff, w):  # noqa: F811
    case_id = ordered_reorder(w)
    cases = client.get("/exports/cases.csv")
    assert cases.status_code == 200 and cases.headers["content-type"].startswith("text/csv") and "attachment" in cases.headers["content-disposition"]
    assert parse(cases)[0] == exports.COLUMNS["cases"] and any("CCTV camera" in r[2] for r in parse(cases)[1:])
    pos = parse(client.get("/exports/purchase-orders.csv"))
    assert pos[0] == exports.COLUMNS["purchase-orders"] and len(pos) == 2 and pos[1][0].startswith("PO-") and pos[1][1].startswith("REQ-")
    assert parse(client.get("/exports/invoices.csv")) == [exports.COLUMNS["invoices"]]                      # none yet: header only
    stock = parse(client.get("/exports/stock.csv"))
    assert stock[0] == exports.COLUMNS["stock"] and {"CCTV camera", "Laptop"} <= {r[0] for r in stock[1:]}
    assert case_id


def test_a_spreadsheet_formula_in_a_supplier_or_item_name_comes_out_as_text(staff, w):  # noqa: F811
    w.add_stock("=1+1", 3)
    assert any(r[0] == "'=1+1" for r in parse(client.get("/exports/stock.csv"))[1:])


def test_a_requester_gets_only_their_own_cases_and_nothing_else(monkeypatch, w):  # noqa: F811
    mine, theirs = w.submit("10 laptops", requester="ravi@x.co"), w.submit("50 cameras", requester="other@x.co")
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: permission in ("cases:read", "cases:create"))
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="ravi@x.co", role="u_requester")
    try:
        rows = parse(client.get("/exports/cases.csv"))[1:]
        assert [r[1] for r in rows] == ["ravi@x.co"] and "cameras" not in "".join(",".join(r) for r in rows).lower()
        for path in ("purchase-orders", "invoices", "stock"):
            assert client.get(f"/exports/{path}.csv").status_code == 403, path
    finally:
        app.dependency_overrides.clear()
    assert mine and theirs


def test_someone_who_may_not_even_read_cases_gets_403_and_signed_out_gets_401(monkeypatch, w):  # noqa: F811
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: False)
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="nobody", role="u_none")
    try:
        for path in ("cases", "purchase-orders", "invoices", "stock"):
            assert client.get(f"/exports/{path}.csv").status_code == 403, path
    finally:
        app.dependency_overrides.clear()
    for path in ("cases", "purchase-orders", "invoices", "stock"):
        assert client.get(f"/exports/{path}.csv").status_code == 401, path


def test_a_stock_only_person_may_export_stock_but_not_orders(monkeypatch, w):  # noqa: F811
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: permission == "stock:read")
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="stores", role="u_stores")
    try:
        assert client.get("/exports/stock.csv").status_code == 200
        assert client.get("/exports/purchase-orders.csv").status_code == 403 and client.get("/exports/invoices.csv").status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---- Excel (.xlsx) beside the CSV ----------------------------------------------------------------------------------------------------------

def workbook(response):
    import io
    from openpyxl import load_workbook
    assert response.status_code == 200 and response.headers["content-type"] == exports.XLSX_TYPE
    assert response.headers["content-disposition"].endswith('.xlsx"') and response.headers["cache-control"] == "no-store"
    return load_workbook(io.BytesIO(response.content)).active


def test_the_workbook_has_a_bold_header_frozen_row_numbers_as_numbers_and_text_that_can_never_be_a_formula():
    import io
    from openpyxl import load_workbook
    data = exports.to_xlsx("stock", [["=1+1", 5, "pcs", None, 10, 40, True, "Acme", datetime(2026, 10, 9, 8, 30)],
                                     ["Cable, \"red\"", 0, None, None, None, None, False, None, None]])
    sheet = load_workbook(io.BytesIO(data)).active
    assert [c.value for c in sheet[1]] == exports.COLUMNS["stock"] and sheet[1][0].font.bold and sheet.freeze_panes == "A2"
    assert sheet["A2"].value == "=1+1" and sheet["A2"].data_type == "s"                      # stored as TEXT: it shows as written and never calculates
    assert sheet["B2"].value == 5 and sheet["B2"].data_type == "n" and sheet["G2"].value == "Yes" and sheet["I2"].value == "2026-10-09 08:30"
    assert sheet["A3"].value == 'Cable, "red"' and sheet["B3"].value == 0 and sheet.max_row == 3


def test_every_kind_can_be_written_as_a_workbook_with_its_header(staff, w):  # noqa: F811
    ordered_reorder(w)
    for kind, path in (("cases", "cases"), ("purchase-orders", "purchase-orders"), ("invoices", "invoices"), ("stock", "stock")):
        sheet = workbook(client.get(f"/exports/{path}.xlsx"))
        assert [c.value for c in sheet[1]] == exports.COLUMNS[kind], kind
    assert workbook(client.get("/exports/purchase-orders.xlsx")).max_row == 2                   # header + the one order


def test_the_excel_exports_have_the_same_permissions_as_the_csv_ones(monkeypatch, w):  # noqa: F811
    mine = w.submit("10 laptops", requester="ravi@x.co")
    w.submit("50 cameras", requester="other@x.co")
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: permission in ("cases:read", "cases:create"))
    app.dependency_overrides[deps.get_current_user] = lambda: CurrentUser(user_id="9", username="ravi@x.co", role="u_requester")
    try:
        sheet = workbook(client.get("/exports/cases.xlsx"))
        assert [r[1].value for r in sheet.iter_rows(min_row=2)] == ["ravi@x.co"]                # only their own case
        for path in ("purchase-orders", "invoices", "stock"):
            assert client.get(f"/exports/{path}.xlsx").status_code == 403, path
    finally:
        app.dependency_overrides.clear()
    for path in ("cases", "purchase-orders", "invoices", "stock"):
        assert client.get(f"/exports/{path}.xlsx").status_code == 401, path
    assert mine


def test_an_excel_export_is_audited_with_its_format(staff, w, monkeypatch):  # noqa: F811
    from app.controllers import export_controller
    seen = []
    monkeypatch.setattr(export_controller.audit, "record", lambda action, **k: seen.append((action, k["detail"])))
    client.get("/exports/stock.xlsx")
    client.get("/exports/stock.csv")
    assert seen == [("export.stock", {"rows": seen[0][1]["rows"], "format": "xlsx"}), ("export.stock", {"rows": seen[1][1]["rows"], "format": "csv"})]


# ---- the Purchase orders and Invoices lists --------------------------------------------------------------------------------------------------

def test_the_purchase_order_list_has_the_case_number_and_is_staff_only(staff, w, monkeypatch):  # noqa: F811
    case_id = ordered_reorder(w)
    rows = client.get("/purchase-orders").json()
    assert len(rows) == 1 and rows[0]["po_number"].startswith("PO-") and rows[0]["case_id"].lower() == case_id.lower() and rows[0]["case_number"].startswith("REQ-")
    monkeypatch.setattr(deps.access, "has_permission", lambda role, permission: False)
    assert client.get("/purchase-orders").status_code == 403
    app.dependency_overrides.clear()
    assert client.get("/purchase-orders").status_code == 401


def test_the_invoice_list_carries_the_case_number(staff, w):  # noqa: F811
    from app.orchestrator import case_pipeline
    case_id = ordered_reorder(w)
    case_pipeline.confirm_delivery(case_id, "recv", None)
    w.reply(case_id, "Acme", "Invoice INV-1 for PO-1001. Total Rs 42,000. 30 x CCTV camera.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    rows = client.get("/invoices").json()
    assert rows and rows[0]["case_number"].startswith("REQ-")
