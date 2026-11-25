"""A supplier's document is the input: scans and photos are read by the AI, an unreadable one is never silent, and a document is matched to its order by the
PO number written in it (no case tag needed)."""

import base64
import io

import pytest
from PIL import Image

from app.clients import azure_openai_client
from app.clients.imap_client import parse_message
from app.core import attachments
from app.core.config import settings
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_attachments import email_with, make_image_only_pdf, make_pdf
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source


def fake_picture(text: str) -> str:
    """A page "picture" the test AI can read: the bytes carry their own text (see clients/ai_stub.py)."""
    return base64.b64encode(b"TESTVISION:" + text.encode()).decode()


def scan(text: str, name: str = "scan.pdf") -> dict:
    return {"name": name, "text": "", "images": [fake_picture(text)]}


def jpeg(width: int = 2400, height: int = 1200) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, "JPEG")
    return buffer.getvalue()


# ---- turning a scan or a photo into page pictures ----

def test_a_scanned_pdf_becomes_page_pictures():
    pages = attachments.page_images("scan.pdf", make_image_only_pdf(), 2)
    assert 1 <= len(pages) <= 2 and pages[0][:2] == b"\xff\xd8"           # JPEG


def test_a_photo_is_shrunk_to_a_sensible_width():
    [picture] = attachments.page_images("invoice.jpg", jpeg(3000, 2000), 2)
    assert Image.open(io.BytesIO(picture)).width == attachments.MAX_IMAGE_WIDTH


def test_nothing_that_cannot_be_pictured_ever_raises():
    assert attachments.page_images("broken.pdf", b"not a pdf", 2) == []
    assert attachments.page_images("memo.docx", b"PK..", 2) == []
    assert attachments.page_images("huge.jpg", b"x" * (attachments.MAX_BYTES + 1), 2) == []
    assert attachments.page_images("scan.pdf", make_image_only_pdf(), 0) == []


def test_only_documents_without_text_are_pictured_and_only_a_few_pages():
    items = [{"name": "a.pdf", "text": "Invoice", "images": ["x"]}, {"name": "b.pdf", "text": "", "images": ["1", "2"]}, {"name": "c.pdf", "text": None, "images": ["3"]}]
    assert attachments.collect_images(items, 2) == ["1", "2"]
    assert attachments.collect_images(items, 3) == ["1", "2", "3"]


def test_a_document_the_ai_can_look_at_is_not_reported_as_unreadable():
    assert attachments.unreadable_names([{"name": "scan.pdf", "text": "", "images": ["x"]}, {"name": "bad.pdf", "text": None}]) == ["bad.pdf"]


def test_the_mailbox_reader_keeps_page_pictures_only_when_vision_is_on(monkeypatch):
    message = email_with(subject="x", files=[("scan.pdf", make_image_only_pdf(), "application/pdf"), ("q.pdf", make_pdf("Total Rs 5,000"), "application/pdf")])
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", True)
    scan_entry, text_entry = parse_message(message)["attachments"]
    assert scan_entry["images"] and "images" not in text_entry                # a PDF that has text needs no picture
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", False)
    assert "images" not in parse_message(message)["attachments"][0]


def test_the_ai_client_sends_pictures_as_image_parts():
    assert azure_openai_client._user_message("hello", None) == "hello"
    parts = azure_openai_client._user_message("", ["AAA"])
    assert parts[0]["type"] == "text" and parts[1]["image_url"]["url"] == "data:image/jpeg;base64,AAA"


# ---- the pipeline ----

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def order_placed(w) -> tuple[str, str]:
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id, f"PO-{w.pos[case_id].po_number}"


def delivered(w):
    case_id, po = order_placed(w)
    case_pipeline.confirm_delivery(case_id, "recv", None)
    return case_id, po


def test_a_scanned_quote_is_read_from_its_picture(w):
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", "", attachments=[scan("Total Rs 42,000. Delivery 7 days. Terms: 50% advance")]) == "quoted"
    assert w.quotes[0].price == 42000.0


def test_a_scanned_invoice_is_read_matched_and_closes_the_case(w):
    case_id, po = delivered(w)
    outcome = w.reply(case_id, "Acme", "", subject=f"RE: [OA-{case_id}] Purchase Order {po}",
                      attachments=[scan(f"Invoice INV-9. {po}. 50 x CCTV camera. Total Rs 42,000.")])
    assert outcome == "invoiced" and w.invoices[0].status == "matched" and w.stage(case_id) == "completed"


def test_only_the_first_pages_are_shown_to_the_ai(w, monkeypatch):
    case_id, po = delivered(w)
    seen = {}

    def spy(system, user, temperature=0.1, images=None):
        if images:                                  # (a later call, to classify the reply, has no pictures)
            seen["images"] = images
        return {"is_invoice": False}

    monkeypatch.setattr(azure_openai_client, "ask_json", spy)
    monkeypatch.setattr(settings, "PDF_VISION_MAX_PAGES", 2)
    pages = [{"name": "scan.pdf", "text": "", "images": [fake_picture("p1"), fake_picture("p2"), fake_picture("p3")]}]
    w.reply(case_id, "Acme", "", subject=f"RE: [OA-{case_id}] Purchase Order {po}", attachments=pages)
    assert len(seen["images"]) == 2


def test_an_unreadable_document_is_never_silent(w, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", False)
    case_id, po = delivered(w)
    before = len(w.sent)
    unreadable = [{"name": "scan.pdf", "text": ""}]
    assert w.reply(case_id, "Acme", "", subject=f"RE: [OA-{case_id}] Purchase Order {po}", attachments=unreadable) == "empty"
    assert any(e.event_type == "document.unreadable" and "scan.pdf" in e.payload["files"] for e in w.events[case_id])
    new = w.sent[before:]
    assert any("could not be read" in m[2] and "scan.pdf" in m[2] for m in new if m[0] != "acme@vendor.com")        # the team is told
    assert any(m[0] == "acme@vendor.com" and "could not read your document" in m[1] for m in new)                  # and so is the supplier


def test_the_supplier_is_asked_to_resend_at_most_twice_but_the_team_is_told_every_time(w, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", False)
    case_id, po = delivered(w)
    for _ in range(3):
        w.reply(case_id, "Acme", "", subject=f"RE: [OA-{case_id}] Purchase Order {po}", attachments=[{"name": "scan.pdf", "text": ""}])
    assert sum(1 for m in w.sent if m[0] == "acme@vendor.com" and "could not read your document" in m[1]) == 2
    assert sum(1 for e in w.events[case_id] if e.event_type == "document.unreadable") == 3


def test_an_unreadable_quote_is_flagged_too(w, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", False)
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "scan.pdf", "text": ""}]) == "empty"
    assert any(e.event_type == "document.unreadable" for e in w.events[case_id])
    assert any(m[0] == "acme@vendor.com" and "could not read your document" in m[1] for m in w.sent)


def test_a_picture_the_ai_cannot_read_is_not_treated_as_an_invoice_and_the_supplier_is_asked(w):
    case_id, po = delivered(w)
    blurry = [{"name": "photo.jpg", "text": None, "images": [base64.b64encode(jpeg(400, 300)).decode()]}]
    assert w.reply(case_id, "Acme", "", subject=f"RE: [OA-{case_id}] Purchase Order {po}", attachments=blurry) == "vendor_reply"
    assert w.invoices == []
    assert any(e.event_type == "invoice.details_requested" for e in w.events[case_id])


# ---- finding the order from the document itself ----

def test_a_document_with_no_case_tag_finds_its_order_from_the_po_number(w):
    case_id, po = delivered(w)
    outcome = w.reply(case_id, "Acme", f"Invoice INV-5. {po}. 50 x CCTV camera. Total Rs 42,000.", tagged=False)
    assert outcome == "invoiced" and w.invoices[0].status == "matched" and w.stage(case_id) == "completed"


def test_the_po_number_can_come_from_the_attached_document(w):
    case_id, po = delivered(w)
    outcome = w.reply(case_id, "Acme", "Invoice attached.", tagged=False,
                      attachments=[{"name": "inv.pdf", "text": f"Invoice INV-6. {po}. 50 x CCTV camera. Total Rs 42,000."}])
    assert outcome == "invoiced" and w.stage(case_id) == "completed"


def test_nobody_can_attach_a_document_to_someone_elses_order(w):
    case_id, po = delivered(w)
    assert w.reply(case_id, "Globex", f"Invoice INV-7. {po}. 50 x CCTV camera. Total Rs 42,000.", tagged=False) == "unmatched_document"   # Globex quoting Acme's order
    assert w.invoices == [] and w.stage(case_id) == "delivered"                                                                          # Acme's order is untouched; a person looks


def test_a_document_that_mentions_no_known_order_is_not_matched(w):
    case_id, po = delivered(w)
    assert w.reply(case_id, "Acme", "Invoice INV-8. PO-99999. Total Rs 42,000.", tagged=False) == "unmatched_document"     # kept for a person, not dropped
    assert w.invoices == []


# ---- the supplier writes about money but it is not an invoice ----

def test_money_without_invoice_details_gets_one_polite_request_for_them(w):
    case_id, po = delivered(w)
    typed = f"PO: {po}\nItem: CCTV camera x 50\nTotal: ₹42,000\nUnit price: ₹840"          # what the supplier really sent: no invoice number
    assert w.reply(case_id, "Acme", typed, subject=f"RE: [OA-{case_id}] Purchase Order {po}") == "vendor_reply"
    assert w.invoices == []
    assert sum(1 for m in w.sent if m[0] == "acme@vendor.com" and "Invoice details needed" in m[1]) == 1
    w.reply(case_id, "Acme", typed, subject=f"RE: [OA-{case_id}] Purchase Order {po}")                  # again within a day: not nagged twice
    assert sum(1 for m in w.sent if m[0] == "acme@vendor.com" and "Invoice details needed" in m[1]) == 1


def test_short_replies_and_replies_before_the_goods_arrive_are_left_alone(w):
    case_id, po = order_placed(w)                                                                     # goods not received yet
    w.reply(case_id, "Acme", "Total Rs 42,000, as agreed.", subject=f"RE: [OA-{case_id}] Purchase Order {po}")
    case_pipeline.confirm_delivery(case_id, "recv", None)
    for short in ("Confirmed!", "Delivered", "Thanks"):
        w.reply(case_id, "Acme", short, subject=f"RE: [OA-{case_id}] Purchase Order {po}")
    assert not [m for m in w.sent if "Invoice details needed" in m[1]]


def test_the_corrected_invoice_after_the_request_is_matched(w):
    case_id, po = delivered(w)
    w.reply(case_id, "Acme", f"PO: {po}\nTotal: ₹42,000", subject=f"RE: [OA-{case_id}] Purchase Order {po}")
    w.reply(case_id, "Acme", f"Invoice INV-11. {po}. 50 x CCTV camera. Total Rs 42,000.", subject=f"RE: [OA-{case_id}] Purchase Order {po}")
    assert w.invoices[0].status == "matched" and w.stage(case_id) == "completed"


def test_the_new_case_events_have_readable_labels():
    from app.core.agent_flow import _DOMAIN_FEED
    for kind in ("document.unreadable", "document.resend_requested", "invoice.details_requested"):
        assert kind in _DOMAIN_FEED


def test_the_new_settings_can_be_changed_in_settings():
    from app.core.tunables import CATALOG
    keys = {t.key for t in CATALOG}
    assert {"PDF_VISION_ENABLED", "PDF_VISION_MAX_PAGES"} <= keys


# ---- a scan with a cover note ("quote attached") is the usual real mail ----

def test_a_scanned_quote_is_read_even_when_the_mail_has_a_cover_note(w):
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", "Please find our quotation attached.", attachments=[scan("Total Rs 42,000. Delivery 7 days. Terms: 50% advance")]) == "quoted"
    assert w.quotes[0].price == 42000.0
    assert not any(e.event_type == "quote.no_price" for e in w.events[case_id])


def test_a_scanned_invoice_is_read_even_when_the_mail_has_a_cover_note(w):
    case_id, po = delivered(w)
    outcome = w.reply(case_id, "Acme", "Invoice attached, please process.", subject=f"RE: [OA-{case_id}] Purchase Order {po}",
                      attachments=[scan(f"Invoice INV-9. {po}. 50 x CCTV camera. Total Rs 42,000.")])
    assert outcome == "invoiced" and w.invoices[0].status == "matched"


def test_a_cover_note_with_an_unreadable_file_is_an_unreadable_document_not_a_missing_price(w, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", False)
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", "Quote attached.", attachments=[{"name": "scan.pdf", "text": ""}]) == "empty"
    types = [e.event_type for e in w.events[case_id]]
    assert "document.unreadable" in types and "quote.no_price" not in types


def test_a_cover_note_that_states_a_price_still_stands_even_if_the_file_is_unreadable(w, monkeypatch):
    monkeypatch.setattr(settings, "PDF_VISION_ENABLED", False)
    case_id = w.submit("50 cameras")
    assert w.reply(case_id, "Acme", "Our price is Rs 42,000, delivery 7 days. Details in the attached scan.", attachments=[{"name": "scan.pdf", "text": ""}]) == "quoted"
