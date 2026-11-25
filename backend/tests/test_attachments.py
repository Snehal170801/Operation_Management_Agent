"""Quotes and invoices that arrive as files (PDF / Excel / CSV), and as HTML-only emails.
The files are generated here (real PDF and .xlsx bytes) and run through the real reader and pipeline."""

import io
from email.message import EmailMessage

import pytest
from fpdf import FPDF
from openpyxl import Workbook

from app.clients.imap_client import parse_message
from app.core import attachments
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world


# ---------- helpers: real file bytes ----------

def make_pdf(*lines: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in lines:
        pdf.cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def make_image_only_pdf() -> bytes:
    """Like a scanned document: a page with graphics but no text layer."""
    pdf = FPDF()
    pdf.add_page()
    pdf.rect(20, 20, 100, 60, style="F")
    return bytes(pdf.output())


def make_xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def email_with(*, subject, body="", sender="acme@vendor.com", files=(), html=None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, "pilot@co.com", subject
    msg.set_content(body or " ")
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, kind in files:
        maintype, subtype = kind.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg


# ---------- reading each file type ----------

def test_a_pdf_is_read():
    text = attachments.extract_text("quote.pdf", make_pdf("Total Rs 42,000. Delivery 7 days.", "Terms: 50% advance"))
    assert "Total Rs 42,000" in text and "50% advance" in text


def test_an_excel_sheet_is_read_row_by_row():
    text = attachments.extract_text("quote.xlsx", make_xlsx([["Item", "Qty", "Price"], ["CCTV camera", 50, 42000]]))
    assert "Item | Qty | Price" in text and "CCTV camera | 50 | 42000" in text


def test_a_csv_is_tidied_into_rows():
    text = attachments.extract_text("q.csv", b"Item,Qty,Price\nCCTV camera,50,42000\n")
    assert "CCTV camera | 50 | 42000" in text


def test_a_text_file_is_read():
    assert attachments.extract_text("note.txt", b"Total Rs 42,000") == "Total Rs 42,000"


def test_a_scanned_pdf_has_no_text():
    assert attachments.extract_text("scan.pdf", make_image_only_pdf()) == ""


@pytest.mark.parametrize("name,data", [
    pytest.param("broken.pdf", b"this is not a pdf", id="corrupt-pdf"),
    pytest.param("broken.xlsx", b"this is not a workbook", id="corrupt-xlsx"),
    pytest.param("memo.docx", b"PK" + bytes([3, 4]) + b"...", id="unsupported-docx"),
    pytest.param("photo.jpg", bytes([0xFF, 0xD8, 0xFF]), id="image"),
    pytest.param("huge.txt", b"x" * (attachments.MAX_BYTES + 1), id="oversize"),
])
def test_unreadable_files_return_none_instead_of_raising(name, data):
    assert attachments.extract_text(name, data) is None


def test_one_files_text_is_capped():
    long = ("word " * 5000).encode()
    assert len(attachments.extract_text("big.txt", long)) == attachments.MAX_CHARS_PER_FILE


def test_combined_text_is_capped_and_labelled():
    files = [{"name": f"f{i}.txt", "text": "y" * 3000} for i in range(5)]
    combined = attachments.combine(files)
    assert len(combined) <= attachments.MAX_TOTAL_CHARS + 50 and "[Attachment: f0.txt]" in combined


def test_unreadable_files_are_reported_by_name():
    files = [{"name": "ok.txt", "text": "hello"}, {"name": "scan.pdf", "text": ""}, {"name": "x.docx", "text": None}]
    assert attachments.unreadable_names(files) == ["scan.pdf", "x.docx"]
    assert "ok.txt" in attachments.combine(files) and "scan.pdf" not in attachments.combine(files)


# ---------- parsing a whole email ----------

def test_attachments_are_pulled_out_of_a_real_email():
    parsed = parse_message(email_with(subject="RE: quote", body="Please see attached.",
                                      files=[("quote.pdf", make_pdf("Total Rs 42,000."), "application/pdf")]))
    assert parsed["from_email"] == "acme@vendor.com" and "Please see attached" in parsed["body"]
    assert parsed["attachments"][0]["name"] == "quote.pdf"
    assert "Total Rs 42,000" in parsed["attachments"][0]["text"]


def test_an_html_only_email_is_still_read():
    msg = EmailMessage()
    msg["From"], msg["Subject"] = "acme@vendor.com", "RE: quote"
    msg.set_content("<html><body><style>p{color:red}</style><p>Total Rs <b>42,000</b></p>"
                    "<p>Delivery 7 days</p></body></html>", subtype="html")
    body = parse_message(msg)["body"]
    assert "Total Rs 42,000" in body and "Delivery 7 days" in body and "color:red" not in body


def test_plain_text_is_preferred_over_html():
    parsed = parse_message(email_with(subject="x", body="plain version", html="<p>html version</p>"))
    assert "plain version" in parsed["body"]


# ---------- through the real pipeline ----------

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def deliver(msg: EmailMessage) -> str:
    return case_pipeline.ingest_quote_email(parse_message(msg))


def test_a_quote_sent_only_as_a_pdf_is_read_and_recorded(w):
    case_id = w.submit("50 cameras")
    outcome = deliver(email_with(
        subject=f"RE: [OA-{case_id}] Request for quotation", body="",
        files=[("quote.pdf", make_pdf("Total Rs 42,000. Delivery 7 days.", "Terms: 50% advance"), "application/pdf")]))
    assert outcome == "quoted"
    quote = w.quotes[0]
    assert quote.price == 42000.0 and quote.lead_time_days == 7 and quote.terms == "50% advance"


def test_a_quote_in_an_excel_file_is_read(w):
    case_id = w.submit("50 cameras")
    xlsx = make_xlsx([["Quotation"], ["Total Rs 45,000. Delivery 5 days. Terms: net 30"]])
    assert deliver(email_with(subject=f"RE: [OA-{case_id}] Request for quotation", sender="globex@vendor.com",
                              files=[("q.xlsx", xlsx, "application/octet-stream")])) == "quoted"
    assert w.quotes[0].price == 45000.0 and w.quotes[0].vendor_name == "Globex"


def test_words_and_a_file_are_combined(w):
    case_id = w.submit("50 cameras")
    deliver(email_with(subject=f"RE: [OA-{case_id}] Request for quotation", body="Terms are as follows.",
                       files=[("q.pdf", make_pdf("Total Rs 42,000. Delivery 7 days."), "application/pdf")]))
    assert w.quotes[0].price == 42000.0


def test_a_scanned_pdf_cannot_be_read_so_a_person_is_pointed_to_it(w, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", False)           # (with it on, the AI looks at the page picture: see test_pdf_intake.py)
    case_id = w.submit("50 cameras")
    outcome = deliver(email_with(subject=f"RE: [OA-{case_id}] Request for quotation", body="",
                                 files=[("scan.pdf", make_image_only_pdf(), "application/pdf")]))
    assert outcome == "empty" and w.quotes == []
    event = next(e for e in w.events[case_id] if e.event_type == "quote.email_ignored")
    assert "scan.pdf" in event.payload["reason"] and "by hand" in event.payload["reason"]


def test_an_invoice_attached_as_a_pdf_is_matched_and_closes_the_case(w):
    case_id = w.submit("50 cameras")
    for vendor, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: 50% advance",
                         "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, vendor, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None)

    invoice_pdf = make_pdf("Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.")
    outcome = deliver(email_with(subject=f"RE: [OA-{case_id}] Purchase Order PO-1001", body="Invoice attached.",
                                 files=[("INV-7.pdf", invoice_pdf, "application/pdf")]))
    assert outcome in ("invoiced",)
    assert w.invoices[0].status == "matched" and w.stage(case_id) == "completed"
