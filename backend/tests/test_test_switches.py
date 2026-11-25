"""The test-only switches (a folder instead of the mailbox, a stand-in for the AI) and the guard that keeps them away from real data."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.clients import ai_stub, azure_openai_client, email_client, imap_client, test_mailbox
from app.core import test_switches as ts
from app.core.config import settings
from app.core.email_parsing import REF_PREFIX

from .fake_world import World, standard_world


# ---- the guard ----

def test_nothing_is_checked_when_no_test_switch_is_on():
    assert ts.problems("production", "opetional_agents", "", False, True) == []


@pytest.mark.parametrize("mail_dir,ai", [("some/dir", False), ("", True), ("some/dir", True)])
def test_a_test_database_in_development_is_allowed(mail_dir, ai):
    assert ts.problems("development", "opetional_agents_test", mail_dir, ai, False) == []


def test_each_unsafe_combination_is_named():
    assert any("production" in p for p in ts.problems("production", "x_test", "d", False, False))
    assert any("_test" in p for p in ts.problems("development", "opetional_agents", "d", False, False))
    assert any("CALL_AFTER_EMAIL" in p for p in ts.problems("development", "x_test", "", True, True))
    assert len(ts.problems("production", "opetional_agents", "d", True, True)) == 3
    assert ts.problems("PRODUCTION ", "x_test", "d", False, False)                  # case and spaces do not slip past it


def run_config(**env):
    base = {**os.environ, "SQL_SERVER": "s", "SQL_DRIVER": "d", "SQL_TRUSTED_CONNECTION": "yes", "JWT_SECRET": "x" * 40}
    for k in ("TEST_MAIL_DIR", "TEST_AI_STUB", "ENVIRONMENT", "CALL_AFTER_EMAIL"):
        base.pop(k, None)
    return subprocess.run([sys.executable, "-c", "import app.core.config"], env={**base, **env}, capture_output=True, text=True, cwd=Path(__file__).parent.parent)


def test_the_app_refuses_to_load_with_a_test_switch_on_a_real_database():
    done = run_config(SQL_DATABASE="opetional_agents", TEST_AI_STUB="true")
    assert done.returncode != 0 and "Refusing to start" in done.stderr and "_test" in done.stderr


def test_the_app_refuses_to_load_with_a_test_switch_in_production():
    done = run_config(SQL_DATABASE="x_test", ENVIRONMENT="production", TEST_MAIL_DIR="folder")
    assert done.returncode != 0 and "production" in done.stderr


def test_the_app_loads_for_a_test_database_and_for_normal_use():
    assert run_config(SQL_DATABASE="x_test", TEST_AI_STUB="true", TEST_MAIL_DIR="folder").returncode == 0
    assert run_config(SQL_DATABASE="opetional_agents").returncode == 0               # nothing switched on: the real setup is untouched


# ---- the folder mailbox ----

@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TEST_MAIL_DIR", str(tmp_path))
    return str(tmp_path)


def test_sending_an_email_writes_a_file_and_never_touches_smtp(box, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_client.smtplib, "SMTP", lambda *a, **k: pytest.fail("a test run must never use SMTP"))
    email_client.send_email("a@x.co", "Hello", "Body text", html="<b>Body</b>")
    sent = test_mailbox.read_outbox(box)
    assert len(sent) == 1 and sent[0]["to"] == "a@x.co" and sent[0]["subject"] == "Hello" and sent[0]["html"] == "<b>Body</b>"


def test_the_outbox_can_be_filtered_by_address_and_subject(box):
    email_client.send_email("a@x.co", "Quote for racks", "1")
    email_client.send_email("b@x.co", "Purchase order", "2")
    assert [m["body"] for m in test_mailbox.read_outbox(box, to="B@X.CO")] == ["2"]
    assert [m["body"] for m in test_mailbox.read_outbox(box, subject_contains="quote")] == ["1"]


def test_a_supplier_reply_is_read_once_through_the_normal_reader(box):
    email_client.send_email("acme@x.co", f"Quote request {REF_PREFIX}abc123]", "Please quote")
    sent = test_mailbox.read_outbox(box)[0]
    test_mailbox.reply_to(box, sent, "Total Rs 42,000. Delivery 7 days.")
    seen = []
    assert imap_client.process_unseen_replies(seen.append) == 1
    assert seen[0]["from_email"] == "acme@x.co" and seen[0]["subject"].startswith("Re: ") and "42,000" in seen[0]["body"] and seen[0]["outbound"] is False
    assert imap_client.process_unseen_replies(seen.append) == 0                      # already read
    assert len(list((Path(box) / "inbox" / "processed").glob("*.json"))) == 1


def test_mail_without_our_case_tag_is_ignored_but_a_bounce_is_not(box):
    test_mailbox.drop_inbound(box, "someone@x.co", "Lunch?", "hello")
    test_mailbox.drop_inbound(box, "MAILER-DAEMON@x.co", "Undelivered Mail Returned to Sender", "550 no such user")
    seen = []
    assert imap_client.process_unseen_replies(seen.append) == 1
    assert seen[0]["from_email"] == "mailer-daemon@x.co"
    assert not test_mailbox.has_unseen(box)                                           # the ignored one was filed away too


def test_a_message_that_breaks_the_handler_is_not_read_again(box):
    test_mailbox.drop_inbound(box, "a@x.co", f"Re: {REF_PREFIX}1]", "x")

    def boom(message):
        raise RuntimeError("bad")

    assert imap_client.process_unseen_replies(boom) == 0
    assert not test_mailbox.has_unseen(box)


def test_a_raw_eml_file_is_understood(box):
    raw = f"From: Acme <acme@x.co>\nTo: us@x.co\nSubject: Re: {REF_PREFIX}9]\n\nTotal Rs 5,000".encode()
    (Path(box) / "inbox").mkdir(parents=True, exist_ok=True)
    (Path(box) / "inbox" / "one.eml").write_bytes(raw)
    seen = []
    assert imap_client.process_unseen_replies(seen.append) == 1 and seen[0]["from_email"] == "acme@x.co" and "5,000" in seen[0]["body"]


def test_waiting_for_mail_returns_at_once_when_something_is_there_and_gives_up_otherwise(box):
    assert imap_client.wait_for_new_mail(0) is False
    test_mailbox.drop_inbound(box, "a@x.co", "x", "y")
    assert imap_client.wait_for_new_mail(5) is True


def test_nothing_changes_for_normal_use(monkeypatch):
    monkeypatch.setattr(settings, "TEST_MAIL_DIR", "")
    monkeypatch.setattr(settings, "IMAP_HOST", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert imap_client.process_unseen_replies(lambda m: None) == 0 and imap_client.wait_for_new_mail(0) is False
    email_client.send_email("a@x.co", "s", "b")                                       # the old dry run: logs only


# ---- the AI stand-in ----

def test_a_plain_request_is_read_with_simple_patterns():
    out = ai_stub.ask_json("You are the Purchase Agent", "Need 8 steel storage racks for the warehouse, urgent, needed by 2026-10-20")
    assert out["items"] == [{"description": "steel storage racks", "quantity": 8}]
    assert out["urgent"] is True and out["needed_by"] == "2026-10-20"


def test_a_request_can_say_exactly_what_it_means():
    text = 'TESTJSON: {"items": [{"description": "Chair", "quantity": 3}], "cost_center": "IT"}'
    assert ai_stub.ask_json("You are the Purchase Agent", text) == {"items": [{"description": "Chair", "quantity": 3}], "cost_center": "IT"}


def test_quotes_are_read_in_rupees_in_any_common_spelling():
    for text in ("Total Rs 42,000. Delivery 7 days. Terms: 50% advance", "Total ₹42,000. Delivery 7 days. Terms: 50% advance", "Total INR 42,000. Delivery 7 days. Terms: 50% advance"):
        out = ai_stub.ask_json("Read this raw vendor quote", text)
        assert out == {"price": 42000.0, "valid_days": None, "lead_time_days": 7, "terms": "50% advance"}
    assert ai_stub.ask_json("raw vendor quote", "we are thinking about it")["price"] is None


def test_ranking_is_by_price_with_a_reason_for_each():
    quotes = [{"vendor_id": "a", "vendor_name": "Acme", "price": 50.0}, {"vendor_id": "b", "vendor_name": "Globex", "price": 40.0}, {"vendor_id": "c", "vendor_name": "None", "price": None}]
    out = ai_stub.ask_json("Rank ALL the vendors", "Quotes: " + repr(quotes))
    assert [r["vendor_id"] for r in out["ranking"]] == ["b", "a"] and out["recommended_vendor_id"] == "b" and all(r["reason"] for r in out["ranking"])


def test_supplier_replies_to_an_order_are_classified():
    po = "You are the PO Agent. Read the reply"
    assert ai_stub.ask_json(po, "We confirm the order")["kind"] == "confirmed"
    assert ai_stub.ask_json(po, "The price has gone up, new price 99,000")["new_price"] == 99000.0
    assert ai_stub.ask_json(po, "ok thanks")["kind"] == "other"
    cancel = "You are the PO Agent. The buyer wants to CANCEL a purchase order"
    assert ai_stub.ask_json(cancel, "It is already shipped")["kind"] == "refused" and ai_stub.ask_json(cancel, "No problem, cancelled")["kind"] == "agreed"


def test_an_invoice_is_read_and_anything_else_is_not_an_invoice():
    out = ai_stub.ask_json("You are the Invoice Agent", "Invoice INV-77. PO-1005. 8 x Steel rack. Total Rs 70,000.")
    assert out["is_invoice"] and out["invoice_number"] == "INV-77" and out["total_amount"] == 70000.0 and out["po_number"] == "PO-1005"
    assert ai_stub.ask_json("You are the Invoice Agent", "Thanks, delivered.")["is_invoice"] is False


def test_stock_matching_never_guesses_and_an_unknown_prompt_is_a_loud_error():
    assert ai_stub.ask_json("You are the Procurement Agent", "Requested item: fan\nStock items: ['Ceiling fan']") == {"stock_item": None}
    with pytest.raises(AssertionError):
        ai_stub.ask_json("Something new", "x")


def test_with_the_switch_on_the_real_client_is_never_called(monkeypatch):
    class Real:
        def __getattr__(self, name):
            pytest.fail("the real Azure OpenAI client must not be used")

    monkeypatch.setattr(settings, "TEST_AI_STUB", True)
    monkeypatch.setattr(azure_openai_client, "_client", Real())
    assert azure_openai_client.ask_json("You are the Procurement Agent", "Requested item: x") == {"stock_item": None}
    assert azure_openai_client.ask_text("s", "u") == "(test summary)"


# ---- the stand-ins really drive the whole pipeline ----

def test_the_stub_ai_and_the_folder_mailbox_run_a_request_into_approval(monkeypatch, tmp_path):
    w: World = standard_world(monkeypatch)
    monkeypatch.setattr(azure_openai_client, "ask_json", ai_stub.ask_json)          # replace the in-memory fake AI with the real stand-in
    case_id = w.submit("Need 50 CCTV cameras for the new site")
    assert w.stage(case_id) == "awaiting_quotes"                                     # 20 on the shelf: not enough
    assert w.requests[case_id].raw_request.startswith("Need 50 CCTV cameras")
    assert [(i.description, i.quantity) for i in next(iter(w.items.values()))][-1] == ("CCTV cameras", 50)
    for vendor in ("Acme", "Globex"):
        assert w.reply(case_id, vendor, "Total ₹90,000. Delivery 7 days. Terms: 50% advance") == "quoted"
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval"                                   # over the auto-approve limit, so a person decides
