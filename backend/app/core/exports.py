"""CSV exports of cases, purchase orders, invoices and stock. Pure functions: rows in, bytes out.

The file opens in Excel (UTF-8 with a byte-order mark, so names and the rupee sign survive). Any text that a spreadsheet would run as a
formula (starts with = + - @, a tab or a carriage return) is prefixed with an apostrophe: supplier names and item descriptions come from
outside, and a cell such as =HYPERLINK(...) must stay text."""

import csv
import io
from datetime import date, datetime

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")

COLUMNS: dict[str, list[str]] = {
    "cases": ["Case number", "Requester", "Items", "Stage", "Status", "Urgent", "Needed by", "Created", "Updated"],
    "purchase-orders": ["PO number", "Case number", "Supplier", "Total amount", "Tax", "Total with tax", "Status", "Delivery status", "Expected delivery", "Created", "Sent",
                        "Confirmed by supplier", "Delivered"],
    "invoices": ["Invoice number", "PO number", "Case number", "Supplier", "Total amount", "Tax shown", "Status", "Issues", "Source", "Decided by", "Received", "Decided"],
    "stock": ["Item", "Quantity", "Unit", "Category", "Low-stock level", "Order-up-to level", "Low", "Preferred supplier", "Updated"],
}


def safe_cell(value) -> str | int | float:
    """One cell: numbers stay numbers, dates become 'YYYY-MM-DD HH:MM', None is empty, text that could run as a formula is defused."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%d %H:%M}"
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    text = str(value)
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def to_csv(kind: str, rows: list[list]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(COLUMNS[kind])
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_COLUMN_WIDTH = 60


def _plain(value):
    """One cell for Excel: numbers stay numbers, dates become text like the CSV, text stays EXACTLY as it is (see to_xlsx for why no apostrophe)."""
    cell = safe_cell(value)
    if isinstance(cell, str) and cell.startswith("'") and isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return value
    return cell


def to_xlsx(kind: str, rows: list[list]) -> bytes:
    """The same table as the CSV, as an Excel workbook: bold header, frozen first row, sensible column widths, numbers as numbers. Text is stored as
    TEXT (data type 's'), so a supplier or item name that starts with = + - @ can never run as a formula, and shows as written."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = kind.replace("-", " ").title()[:31]
    header = COLUMNS[kind]
    sheet.append(header)
    for row in rows:
        sheet.append([_plain(v) for v in row])
    for row in sheet.iter_rows(min_row=1):
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for index, title in enumerate(header, start=1):
        longest = max([len(str(title))] + [len(str(r[index - 1])) for r in rows if index - 1 < len(r) and r[index - 1] is not None])
        sheet.column_dimensions[get_column_letter(index)].width = min(max(longest + 2, 10), MAX_COLUMN_WIDTH)
    import io
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def file_name(kind: str, today: date, extension: str = "csv") -> str:
    return f"{kind}-{today:%Y-%m-%d}.{extension}"


def case_rows(cases: list[dict]) -> list[list]:
    return [[c.get("case_number"), c.get("requester_id"), c.get("items_summary"), c.get("stage"), c.get("status"), bool(c.get("urgent")),
             c.get("needed_by"), c.get("created_at"), c.get("updated_at")] for c in cases]


def purchase_order_rows(pos: list[dict], case_numbers: dict[str, str]) -> list[list]:
    return [[p["po_number"], case_numbers.get(p["case_id"].lower()), p["vendor_name"], p.get("total_amount"), p.get("tax_amount"), p.get("total_with_tax"), p.get("status"), p.get("delivery_status"),
             p.get("expected_delivery_date"), p.get("created_at"), p.get("sent_at"), p.get("acknowledged_at"), p.get("delivered_at")] for p in pos]


def invoice_rows(invoices: list[dict], case_numbers: dict[str, str]) -> list[list]:
    return [[i.get("invoice_number"), i["po_number"], case_numbers.get(i["case_id"].lower()), i["vendor_name"], i.get("total_amount"), i.get("tax_amount"), i.get("status"),
             "; ".join(i.get("issues") or []), i.get("source"), i.get("decided_by"), i.get("created_at"), i.get("decided_at")] for i in invoices]


def stock_rows(stock: list) -> list[list]:
    return [[s.item_description, s.quantity_available, s.unit, s.category, s.min_level, s.target_level, bool(s.low), s.preferred_vendor_name,
             getattr(s, "updated_at", None)] for s in stock]
