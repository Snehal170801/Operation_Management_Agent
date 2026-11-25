"""A bounced email to a supplier: stop waiting on them, tell the right team, never retry a dead address."""

import pytest

from app.agents import vendor_agent
from app.core import bounce as bn
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

GMAIL = ("Address not found\n\nYour message wasn't delivered to {addr} because the address couldn't be found, or is unable to receive mail.\n\n"
         "The response was:\n550 5.1.1 The email account that you tried to reach does not exist.\n\nSubject: [OA-{case}] {title}")


def dsn(addr, case, title="Request for quotation", body=GMAIL):
    return {"from_email": "mailer-daemon@googlemail.com", "subject": "Delivery Status Notification (Failure)", "body": body.format(addr=addr, case=case, title=title)}


def test_a_real_bounce_is_recognised_and_read():
    m = dsn("nobody@bad.com", "3f2b8c1a-1111-4222-8333-444455556666")
    assert bn.is_bounce(m)
    info = bn.parse(m)
    assert info["address"] == "nobody@bad.com" and info["case_id"] == "3f2b8c1a-1111-4222-8333-444455556666"
    assert info["permanent"] and info["about"] == "quote" and info["reason"] == "Address not found"
    assert bn.parse(dsn("x@bad.com", "3f2b8c1a-1111-4222-8333-444455556666", "Purchase Order PO-1001"))["about"] == "order"


def test_people_and_out_of_office_replies_are_not_bounces():
    assert not bn.is_bounce({"from_email": "bob@x.com", "subject": "Automatic reply: quotation", "body": "I am out of the office until Monday."})
    assert not bn.is_bounce({"from_email": "bob@x.com", "subject": "RE: [OA-1] Request for quotation", "body": "Total Rs 42,000."})


def test_a_full_mailbox_is_temporary_not_permanent():
    m = {"from_email": "mailer-daemon@x.com", "subject": "Undelivered Mail Returned to Sender", "body": "Your message to bob@x.com was not delivered. Mailbox is full. Try again later. 452 4.2.2"}
    assert bn.is_bounce(m) and bn.parse(m)["permanent"] is False


@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def test_a_bounced_quote_request_stops_the_wait_flags_the_address_and_tells_the_vendor_team(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", QUOTE_42K)
    w.reply(case_id, "Globex", QUOTE_45K)
    initech = w.vendors[w.vendor_id("Initech")]
    assert w.stage(case_id) == "awaiting_quotes"                                   # still waiting on the third
    mark = len(w.sent)
    assert case_pipeline.ingest_quote_email(dsn(initech.email, case_id)) == "bounced"
    assert initech.email_bounced_at is not None and "Address not found" in initech.email_bounce_reason
    assert [r.status for r in w.rfqs if r.vendor_name == "Initech"] == ["bounced"]
    assert "bounced" in w.emails_to("manager@x.co")[-1][2] and "Vendors page" in w.emails_to("manager@x.co")[-1][2]
    assert "email.bounced" in w.event_types(case_id)
    assert w.stage(case_id) in ("po_issued", "vendor_selected", "awaiting_approval")   # everyone who could answer has: it moves on at once


def test_a_bounced_supplier_is_not_emailed_again_until_the_address_changes(w):
    first = w.submit("50 cameras")
    initech = w.vendors[w.vendor_id("Initech")]
    case_pipeline.ingest_quote_email(dsn(initech.email, first))
    mark = len(w.sent)
    w.teach("10 laptops more", [{"description": "Widget", "quantity": 10}])
    w.add_stock("Widget", 0)
    second = w.submit("10 laptops more")
    asked = {m[0] for m in w.sent[mark:] if "Request for quotation" in m[1]}
    assert initech.email not in asked and len(asked) == 2
    w.vendors[initech.vendor_id].email_bounced_at = None                           # (what saving a new address does)
    assert vendor_agent.get_all_vendors()[0] is not None


def test_a_bounced_order_email_is_marked_failed_and_the_po_desk_told(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    po = w.pos[case_id]
    assert case_pipeline.ingest_quote_email(dsn(po.vendor_email, case_id, f"Purchase Order PO-{po.po_number}")) == "bounced"
    assert po.status == "send_failed" and w.stage(case_id) == "po_send_failed"
    assert "order email" in w.emails_to("manager@x.co")[-1][2] and "retry" in w.emails_to("manager@x.co")[-1][2].lower()


def test_a_bounce_with_no_case_reference_finds_the_open_requests_by_supplier(w):
    case_id = w.submit("50 cameras")
    acme = w.vendors[w.vendor_id("Acme")]
    m = dsn(acme.email, "x")
    m["body"] = m["body"].split("Subject:")[0]                                       # the original subject was not quoted
    assert case_pipeline.ingest_quote_email(m) == "bounced"
    assert [r.status for r in w.rfqs if r.vendor_name == "Acme" and r.case_id == case_id] == ["bounced"]


def test_a_temporary_failure_or_a_stranger_changes_nothing(w):
    case_id = w.submit("50 cameras")
    acme = w.vendors[w.vendor_id("Acme")]
    full = {"from_email": "mailer-daemon@x.com", "subject": "Undelivered Mail Returned to Sender", "body": f"Your message to {acme.email} was not delivered. Mailbox is full. Try again later. 452 4.2.2"}
    assert case_pipeline.ingest_quote_email(full) == "bounce_ignored" and acme.email_bounced_at is None
    assert case_pipeline.ingest_quote_email(dsn("stranger@elsewhere.com", case_id)) == "bounce_unknown_address"
    assert all(r.status == "sent" for r in w.rfqs if r.case_id == case_id)


def test_every_supplier_bouncing_stalls_the_request_for_a_person(w):
    case_id = w.submit("50 cameras")
    for v in list(w.vendors.values()):
        case_pipeline.ingest_quote_email(dsn(v.email, case_id))
    assert w.stage(case_id) == "sourcing_stalled" or all(r.status == "bounced" for r in w.rfqs if r.case_id == case_id)


def test_my_work_lists_unreachable_suppliers_for_the_vendor_team(w):
    from datetime import datetime
    from app.core.my_work import build_my_work
    case_id = w.submit("50 cameras")
    case_pipeline.ingest_quote_email(dsn(w.vendors[w.vendor_id("Acme")].email, case_id))
    work = build_my_work("vendor", lambda p: p == "vendors:write", approvals=[], cases=[], deliveries=[], invoices=[], stock=[], now=datetime.utcnow(),
                         bounced_vendors=[v for v in vendor_agent.get_all_vendors() if v.get("email_bounced_at")])
    item = work["queues"][0]["items"][0]
    assert item["urgent"] and "acme@vendor.com" in item["detail"] and item["link"] == "/vendors"
