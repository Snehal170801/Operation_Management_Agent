"""With one shared mailbox the system sends to the inbox it also reads. It must never treat its own
quote requests / purchase orders as supplier replies."""

from email import message_from_bytes
from email.message import EmailMessage

import pytest

from app.clients import email_client
from app.clients.imap_client import parse_message
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world


class FakeSMTP:
    sent: list = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self): pass
    def login(self, *a): pass
    def send_message(self, message): FakeSMTP.sent.append(message)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(email_client.settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(email_client.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_every_email_we_send_carries_the_marker(smtp):
    email_client.send_email("acme@vendor.com", "[OA-x] Request for quotation", "please quote")
    assert smtp.sent[0][email_client.OUTBOUND_HEADER] == "1"


def test_the_marker_survives_the_trip_and_is_recognised_when_read_back(smtp):
    email_client.send_email("me@gmail.com", "[OA-x] Request for quotation", "please quote")
    on_the_wire = message_from_bytes(smtp.sent[0].as_bytes())      # what the mailbox actually stores
    assert parse_message(on_the_wire)["outbound"] is True


def test_a_supplier_reply_is_not_marked_as_ours():
    reply = EmailMessage()
    reply["From"], reply["Subject"] = "acme@vendor.com", "RE: [OA-x] Request for quotation"
    reply.set_content("Total Rs 42,000")
    assert parse_message(reply)["outbound"] is False


@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def test_our_own_request_for_quotation_is_never_recorded_as_a_quote(w):
    case_id = w.submit("50 cameras")
    rfq = next(m for m in w.sent if "Request for quotation" in m[1])
    # the same text coming back through the mailbox, from an address that happens to be a supplier's
    outcome = case_pipeline.ingest_quote_email({
        "from_email": "acme@vendor.com", "subject": rfq[1], "body": rfq[2], "attachments": [], "outbound": True})
    assert outcome == "own_message" and w.quotes == []
    assert "quote.email_ignored" not in w.event_types(case_id)       # and no noise on the timeline


def test_our_own_purchase_order_is_not_read_as_a_supplier_reply(w):
    case_id = w.submit("50 cameras")
    for vendor, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30",
                         "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, vendor, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    po_mail = next(m for m in w.sent if "Purchase Order" in m[1])
    before = len(w.events[case_id])
    outcome = case_pipeline.ingest_quote_email({
        "from_email": "acme@vendor.com", "subject": po_mail[1], "body": po_mail[2], "attachments": [], "outbound": True})
    assert outcome == "own_message" and len(w.events[case_id]) == before and w.invoices == []
