"""A document from a known supplier that names no order we can find is kept for a person to attach to the right case: nothing a supplier sends is dropped."""

import pytest

from app.agents import document_agent
from app.api.routes import unmatched_documents as documents_route
from app.clients import test_mailbox
from app.controllers import unmatched_document_controller as document_controller
from app.core.exceptions import DocumentAlreadyHandled, DocumentNotFound, Forbidden, InvalidInput
from app.models.auth_schemas import CurrentUser
from app.models.document_schemas import AttachDocumentRequest, DismissDocumentRequest
from app.orchestrator import case_pipeline

from .fake_world import World, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source


@pytest.fixture
def w(monkeypatch) -> World:
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    return standard_world(monkeypatch)


ACCOUNTS = CurrentUser(user_id="1", username="accounts", role="u_accounts")


def delivered_order(w) -> tuple[str, str]:
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    case_pipeline.confirm_delivery(case_id, "recv", None)
    return case_id, f"PO-{w.pos[case_id].po_number}"


INVOICE_WITHOUT_ORDER = "Invoice INV-31. 50 x CCTV camera. Total Rs 42,000."          # names no order


def test_a_known_supplier_document_with_no_order_is_kept_and_accounts_are_told(w):
    delivered_order(w)
    before = len(w.sent)
    assert w.reply("", "Acme", INVOICE_WITHOUT_ORDER, tagged=False, attachments=[{"name": "inv.pdf", "text": "Invoice INV-31"}]) == "unmatched_document"
    [doc] = document_controller.list_unmatched()
    assert doc.vendor_name == "Acme" and doc.file_names == ["inv.pdf"] and "INV-31" in doc.summary
    assert any(m[1] == "A supplier document needs a case" and "/documents" in m[2] for m in w.sent[before:])


def test_mail_from_a_stranger_or_a_supplier_newsletter_is_not_kept(w):
    from app.clients import email_client  # noqa: F401
    assert case_pipeline.ingest_quote_email({"from_email": "stranger@nowhere.com", "subject": "Hello", "body": INVOICE_WITHOUT_ORDER}) == "no_case"
    assert w.reply("", "Acme", "Happy Diwali from all of us at Acme!", tagged=False) == "no_case"
    assert document_controller.list_unmatched() == []


def test_attaching_it_to_the_right_case_handles_it_like_a_tagged_reply(w):
    case_id, _po = delivered_order(w)
    w.reply("", "Acme", INVOICE_WITHOUT_ORDER, tagged=False)
    [doc] = document_controller.list_unmatched()
    result = document_controller.attach(doc.document_id, AttachDocumentRequest(case_id=case_id), ACCOUNTS)
    assert result.outcome == "invoiced" and w.invoices[0].status == "matched" and w.stage(case_id) == "completed"
    assert document_controller.list_unmatched() == []
    attached = next(e for e in w.events[case_id] if e.event_type == "document.attached")
    assert attached.payload["by"] == "accounts"


def test_a_case_that_cannot_use_the_document_leaves_it_waiting(w):
    delivered_order(w)
    other = w.submit("10 laptops")                                                      # filled from stock: no supplier was ever asked
    w.reply("", "Acme", INVOICE_WITHOUT_ORDER, tagged=False)
    [doc] = document_controller.list_unmatched()
    with pytest.raises(InvalidInput, match="cannot use this document"):
        document_controller.attach(doc.document_id, AttachDocumentRequest(case_id=other), ACCOUNTS)
    assert len(document_controller.list_unmatched()) == 1


def test_a_document_is_attached_once_and_two_clicks_cannot_both_win(w):
    case_id, _po = delivered_order(w)
    w.reply("", "Acme", INVOICE_WITHOUT_ORDER, tagged=False)
    [doc] = document_controller.list_unmatched()
    document_controller.attach(doc.document_id, AttachDocumentRequest(case_id=case_id), ACCOUNTS)
    with pytest.raises(DocumentAlreadyHandled):
        document_controller.attach(doc.document_id, AttachDocumentRequest(case_id=case_id), ACCOUNTS)
    with pytest.raises(DocumentAlreadyHandled):
        document_controller.dismiss(doc.document_id, DismissDocumentRequest(), ACCOUNTS)


def test_dismissing_removes_it_from_the_list_with_a_note(w):
    delivered_order(w)
    w.reply("", "Acme", INVOICE_WITHOUT_ORDER, tagged=False)
    [doc] = document_controller.list_unmatched()
    document_controller.dismiss(doc.document_id, DismissDocumentRequest(note="a duplicate"), ACCOUNTS)
    assert document_controller.list_unmatched() == [] and w.documents[0].status == "dismissed" and w.documents[0].note == "a duplicate"


def test_an_unknown_document_is_a_clear_error(w):
    with pytest.raises(DocumentNotFound):
        document_agent.get("00000000-0000-0000-0000-000000000000")
    with pytest.raises(DocumentNotFound):
        document_controller.dismiss("00000000-0000-0000-0000-000000000000", DismissDocumentRequest(), ACCOUNTS)


def test_scanned_pages_are_kept_so_a_scanned_document_can_be_read_after_it_is_attached(w):
    import base64
    case_id, po = delivered_order(w)
    picture = base64.b64encode(f"TESTVISION:Invoice INV-32. {po}. 50 x CCTV camera. Total Rs 42,000.".encode()).decode()
    w.reply("", "Acme", "", tagged=False, attachments=[{"name": "scan.pdf", "text": "", "images": [picture]}])
    # (this one names its PO only inside the picture, so it cannot be matched yet: it waits for a person)
    [doc] = document_controller.list_unmatched()
    assert document_controller.attach(doc.document_id, AttachDocumentRequest(case_id=case_id), ACCOUNTS).outcome == "invoiced"
    assert w.stage(case_id) == "completed"


def test_only_accounts_and_the_vendor_team_may_attach_or_dismiss(monkeypatch):
    from app.core import access
    holds = {"invoices:decide": False, "vendors:write": False}
    monkeypatch.setattr(access, "has_permission", lambda role, permission: holds.get(permission, False))
    with pytest.raises(Forbidden):
        documents_route._handler(CurrentUser(user_id="1", username="stores", role="u_stores"))
    holds["vendors:write"] = True
    assert documents_route._handler(CurrentUser(user_id="2", username="vendor", role="u_vendor")).username == "vendor"


# ---- the mailbox reader fetches mail from known suppliers even without a case tag ----

def test_the_test_mailbox_reads_an_untagged_mail_only_from_a_listed_supplier(tmp_path):
    base = str(tmp_path)
    test_mailbox.drop_inbound(base, "acme@vendor.com", "Our invoice", "Invoice INV-1")
    test_mailbox.drop_inbound(base, "stranger@x.com", "Our invoice", "Invoice INV-2")
    seen = []
    assert test_mailbox.process_unseen(base, seen.append, ("acme@vendor.com",)) == 1
    assert seen[0]["from_email"] == "acme@vendor.com"


def test_without_a_supplier_list_untagged_mail_is_still_ignored(tmp_path):
    test_mailbox.drop_inbound(str(tmp_path), "acme@vendor.com", "Our invoice", "Invoice INV-1")
    assert test_mailbox.process_unseen(str(tmp_path), lambda m: None) == 0


def test_the_supplier_list_is_the_vendors_email_addresses(w):
    assert set(case_pipeline.supplier_addresses()) == {"acme@vendor.com", "globex@vendor.com", "initech@vendor.com"}


def test_the_worker_hands_the_supplier_list_to_the_mailbox_reader(w, monkeypatch):
    from app.orchestrator import worker
    seen = {}
    monkeypatch.setattr(worker.imap_client, "process_unseen_replies", lambda handler, senders=(): seen.update(senders=senders) or 0)
    worker.read_mailbox()
    assert "acme@vendor.com" in seen["senders"]


def test_a_document_event_has_a_readable_label():
    from app.core.agent_flow import _DOMAIN_FEED
    assert "document.attached" in _DOMAIN_FEED
