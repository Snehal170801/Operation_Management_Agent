from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents import invoice_agent
from app.core import access, security
from app.core.exceptions import InvoiceAlreadyDecided, NotAnInvoice
from app.core.invoice_policy import evaluate_invoice
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS
from app.main import app
from app.orchestrator import case_pipeline
from app.repositories import role_repository, user_repository

CASE = "3f2b8c1a-1111-4222-8333-444455556666"
PO = {
    "purchase_order_id": "po-id", "po_number": "PO-1001", "vendor_id": "v1", "vendor_name": "Acme",
    "total_amount": 42000.0, "items": [{"description": "Camera", "quantity": 50}],
}


def invoice(**over):
    base = {"invoice_number": "INV-7", "total_amount": 42000.0, "po_number": "PO-1001",
            "items": [{"description": "Camera", "quantity": 50}]}
    return {**base, **over}


def match(inv=None, received=True, duplicate=False, tol=1.0, po=PO):
    return evaluate_invoice(po, inv or invoice(), received, duplicate, tol)


# ---------- policy ----------

def test_clean_invoice_for_received_goods_matches():
    assert match() == ("matched", [])


def test_clean_invoice_before_delivery_is_held_not_flagged():
    status, issues = match(received=False)
    assert status == "on_hold" and "received" in issues[0]


def test_amount_within_tolerance_matches():
    assert match(invoice(total_amount=42300.0))[0] == "matched"  # 0.7% off, tolerance 1%


def test_amount_over_tolerance_is_a_mismatch():
    status, issues = match(invoice(total_amount=46000.0))
    assert status == "mismatch" and "46,000.00" in issues[0] and "42,000.00" in issues[0]


def test_wrong_po_number_is_a_mismatch():
    assert match(invoice(po_number="PO-2002"))[0] == "mismatch"


def test_unlabelled_po_number_is_not_held_against_the_vendor():
    assert match(invoice(po_number=None))[0] == "matched"


def test_quantity_mismatch_is_flagged():
    status, issues = match(invoice(items=[{"description": "Camera", "quantity": 60}]))
    assert status == "mismatch" and "60" in issues[0] and "50" in issues[0]


def test_invoice_without_items_skips_the_quantity_check():
    assert match(invoice(items=[]))[0] == "matched"


@pytest.mark.parametrize("over", [{"invoice_number": None}, {"total_amount": None}])
def test_unreadable_fields_need_a_person(over):
    assert match(invoice(**over))[0] == "mismatch"


def test_duplicate_invoice_is_flagged():
    status, issues = match(duplicate=True)
    assert status == "mismatch" and "duplicate" in issues[0].lower()


def test_po_without_a_total_cannot_be_matched_automatically():
    assert match(po={**PO, "total_amount": None})[0] == "mismatch"


def test_problems_beat_the_receipt_hold():
    assert match(invoice(total_amount=1.0), received=False)[0] == "mismatch"


def test_every_problem_is_reported():
    _, issues = match(invoice(total_amount=1.0, po_number="PO-9"))
    assert len(issues) == 2


# ---------- agent: reading the AI's answer defensively ----------

def test_extraction_cleans_up_messy_ai_output(monkeypatch):
    monkeypatch.setattr(invoice_agent.azure_openai_client, "ask_json", lambda s, t: {
        "is_invoice": True, "invoice_number": "  INV-9 ", "total_amount": "42,000.50",
        "po_number": None, "items": [{"description": "Camera", "quantity": "5"}, {"bad": 1}, "junk"],
    })
    out = invoice_agent.extract("anything")
    assert out == {"is_invoice": True, "invoice_number": "INV-9", "total_amount": 42000.5,
                   "po_number": None, "items": [{"description": "Camera", "quantity": 5}],
                   "subtotal": None, "tax_rate_pct": None, "tax_amount": None}


def test_extraction_never_guesses(monkeypatch):
    monkeypatch.setattr(invoice_agent.azure_openai_client, "ask_json", lambda s, t: {
        "is_invoice": "yes", "invoice_number": "", "total_amount": "lots", "items": None})
    out = invoice_agent.extract("anything")
    assert out["is_invoice"] is False and out["invoice_number"] is None
    assert out["total_amount"] is None and out["items"] == []


def test_a_person_cannot_decide_an_invoice_twice(monkeypatch):
    monkeypatch.setattr(invoice_agent, "get_invoice", lambda iid: {"case_id": CASE})
    monkeypatch.setattr(invoice_agent.invoice_repository, "decide_open", lambda *a: False)
    with pytest.raises(InvoiceAlreadyDecided):
        invoice_agent.decide("i1", True, "mgr@x.co", None)


# ---------- pipeline ----------

def _stub(monkeypatch, *, is_invoice=True, delivered=True, duplicate=False, extracted=None):
    log = SimpleNamespace(recorded=[], alerts=[], closed=[], events=[], rechecked=[], invoices=[])
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "get_purchase_order", lambda cid: PO)
    monkeypatch.setattr(case_pipeline.invoice_agent, "extract", lambda text: extracted or {
        "is_invoice": is_invoice, "invoice_number": "INV-7", "total_amount": 42000.0,
        "po_number": "PO-1001", "items": [{"description": "Camera", "quantity": 50}]})
    monkeypatch.setattr(case_pipeline.invoice_agent, "number_exists", lambda vid, num: duplicate)
    monkeypatch.setattr(case_pipeline.delivery_agent, "get_delivery",
                        lambda cid: {"delivery_status": "delivered" if delivered else "pending"})

    def record(case_id, po, raw, extracted, status, issues, source):
        row = {"invoice_id": "i1", "case_id": case_id, "status": status, "issues": issues, "source": source,
               "invoice_number": extracted["invoice_number"]}
        log.recorded.append(row)
        log.invoices.append(row)
        return row

    monkeypatch.setattr(case_pipeline.invoice_agent, "record", record)
    monkeypatch.setattr(case_pipeline.invoice_agent, "get_invoices", lambda cid: list(log.invoices))
    monkeypatch.setattr(case_pipeline.invoice_agent, "re_evaluate",
                        lambda inv, status, issues: log.rechecked.append((inv["invoice_id"], status)) or
                        inv.update(status=status))
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled",
                        lambda cid, reason, team=None: log.alerts.append(reason))
    monkeypatch.setattr(case_pipeline.operations_agent, "close_case",
                        lambda cid, stage, reason: log.closed.append(stage))
    monkeypatch.setattr(case_pipeline.operations_agent, "set_stage", lambda *a: None)
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event",
                        lambda cid, t, **kw: log.events.append(t))
    return log


def test_clean_invoice_closes_the_case_with_no_human(monkeypatch):
    log = _stub(monkeypatch)
    assert case_pipeline.process_invoice(CASE, "invoice text", "email")["status"] == "matched"
    assert log.closed == ["completed"] and log.alerts == []


def test_mismatched_invoice_alerts_a_human_and_keeps_the_case_open(monkeypatch):
    log = _stub(monkeypatch, extracted={"is_invoice": True, "invoice_number": "INV-7",
                                        "total_amount": 99999.0, "po_number": None, "items": []})
    assert case_pipeline.process_invoice(CASE, "text", "email")["status"] == "mismatch"
    assert log.closed == [] and len(log.alerts) == 1
    assert "INV-7" in log.alerts[0] and "Acme" in log.alerts[0] and "99,999.00" in log.alerts[0]


def test_invoice_before_delivery_waits_quietly(monkeypatch):
    log = _stub(monkeypatch, delivered=False)
    assert case_pipeline.process_invoice(CASE, "text", "email")["status"] == "on_hold"
    assert log.closed == [] and log.alerts == []


def test_confirming_delivery_releases_a_held_invoice_and_closes_the_case(monkeypatch):
    log = _stub(monkeypatch, delivered=False)
    case_pipeline.process_invoice(CASE, "text", "email")  # held

    monkeypatch.setattr(case_pipeline.delivery_agent, "confirm_received",
                        lambda cid, by, note, items=None: {"delivery_status": "delivered"})
    monkeypatch.setattr(case_pipeline.delivery_agent, "get_delivery", lambda cid: {"delivery_status": "delivered"})
    case_pipeline.confirm_delivery(CASE, "mgr@x.co", None)
    assert log.rechecked == [("i1", "matched")] and log.closed == ["completed"]


def test_goods_received_but_no_invoice_yet_keeps_the_case_open(monkeypatch):
    log = _stub(monkeypatch)
    monkeypatch.setattr(case_pipeline.delivery_agent, "confirm_received",
                        lambda cid, by, note, items=None: {"delivery_status": "delivered"})
    case_pipeline.confirm_delivery(CASE, "mgr@x.co", None)
    assert log.closed == []


def test_a_non_invoice_is_rejected_and_nothing_is_recorded(monkeypatch):
    log = _stub(monkeypatch, is_invoice=False)
    with pytest.raises(NotAnInvoice):
        case_pipeline.process_invoice(CASE, "thanks, order received!", "manual")
    assert log.recorded == []


def test_a_person_approving_a_mismatch_closes_the_case(monkeypatch):
    log = _stub(monkeypatch)
    monkeypatch.setattr(case_pipeline.invoice_agent, "decide",
                        lambda iid, approve, by, note: {"invoice_id": iid, "case_id": CASE, "status": "approved"})
    log.invoices.append({"invoice_id": "i1", "case_id": CASE, "status": "approved"})
    case_pipeline.decide_invoice("i1", True, "mgr@x.co", "ok, discount agreed")
    assert log.closed == ["completed"]


def test_a_person_rejecting_an_invoice_does_not_close_the_case(monkeypatch):
    log = _stub(monkeypatch)
    monkeypatch.setattr(case_pipeline.invoice_agent, "decide",
                        lambda iid, approve, by, note: {"invoice_id": iid, "case_id": CASE, "status": "rejected", "vendor_id": "v1"})
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_all_vendors", lambda: [{"vendor_id": "v1", "email": "sales@acme.com"}])
    monkeypatch.setattr(case_pipeline.invoice_agent, "request_corrected_invoice", lambda *a: True)
    case_pipeline.decide_invoice("i1", False, "mgr@x.co", "wrong amount")
    assert log.closed == []


def test_rejecting_an_invoice_asks_the_supplier_for_a_corrected_one(monkeypatch):
    _stub(monkeypatch)
    told = []
    rejected = {"invoice_id": "i1", "case_id": CASE, "status": "rejected", "vendor_id": "V1", "vendor_name": "Acme", "invoice_number": "INV-9",
                "po_number": "PO-1001", "issues": ["Invoice total 120,000.00 differs from the purchase order total 95,000.00."]}
    monkeypatch.setattr(case_pipeline.invoice_agent, "decide", lambda iid, approve, by, note: rejected)
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_all_vendors", lambda: [{"vendor_id": "v1", "email": "sales@acme.com"}])
    monkeypatch.setattr(case_pipeline.invoice_agent, "request_corrected_invoice", lambda inv, email, note: told.append((inv["invoice_number"], email, note)) or True)
    case_pipeline.decide_invoice("i1", False, "mgr@x.co", "wrong amount")
    assert told == [("INV-9", "sales@acme.com", "wrong amount")]


def test_approving_an_invoice_does_not_email_the_supplier(monkeypatch):
    _stub(monkeypatch)
    monkeypatch.setattr(case_pipeline.invoice_agent, "decide", lambda iid, approve, by, note: {"invoice_id": iid, "case_id": CASE, "status": "approved"})
    monkeypatch.setattr(case_pipeline, "_finalise", lambda cid: None)
    monkeypatch.setattr(case_pipeline.invoice_agent, "request_corrected_invoice", lambda *a: (_ for _ in ()).throw(AssertionError("must not email")))
    case_pipeline.decide_invoice("i1", True, "mgr@x.co", None)


def _rejected_invoice():
    return {"invoice_id": "i1", "case_id": CASE, "vendor_name": "Acme", "invoice_number": "INV-9", "po_number": "PO-1001",
            "issues": ["Invoice total 120,000.00 differs from the purchase order total 95,000.00."]}


def test_the_email_to_the_supplier_gives_the_reason_the_note_and_a_subject_that_leads_back_to_the_case(monkeypatch):
    from app.agents import invoice_agent
    sent, events = [], []
    monkeypatch.setattr(invoice_agent.email_client, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(invoice_agent.operations_agent, "publish_event", lambda cid, t, **kw: events.append((t, kw["payload"])))
    assert invoice_agent.request_corrected_invoice(_rejected_invoice(), "sales@acme.com", "Please check the quantity") is True
    to, subject, body = sent[0]
    assert to == "sales@acme.com" and subject.startswith(f"[OA-{CASE}]") and "INV-9" in subject
    assert "differs from the purchase order total" in body and "Please check the quantity" in body and "PO-1001" in body
    assert events == [("invoice.vendor_notified", {"invoice_id": "i1", "vendor": "Acme", "sent": True, "reason": None})]


def test_a_supplier_with_no_email_is_recorded_not_a_crash(monkeypatch):
    from app.agents import invoice_agent
    events = []
    monkeypatch.setattr(invoice_agent.email_client, "send_email", lambda *a: (_ for _ in ()).throw(AssertionError("no address to send to")))
    monkeypatch.setattr(invoice_agent.operations_agent, "publish_event", lambda cid, t, **kw: events.append(kw["payload"]))
    assert invoice_agent.request_corrected_invoice(_rejected_invoice(), None, None) is False
    assert events[0]["sent"] is False and "no email address" in events[0]["reason"]


def test_an_email_that_fails_to_send_never_undoes_the_rejection(monkeypatch):
    from app.agents import invoice_agent
    events = []

    def boom(*a):
        raise OSError("smtp down")
    monkeypatch.setattr(invoice_agent.email_client, "send_email", boom)
    monkeypatch.setattr(invoice_agent.operations_agent, "publish_event", lambda cid, t, **kw: events.append(kw["payload"]))
    assert invoice_agent.request_corrected_invoice(_rejected_invoice(), "sales@acme.com", None) is False
    assert events[0]["sent"] is False and events[0]["reason"] == "The email could not be sent."


# ---------- vendor replies by email ----------

def _mail(body="Invoice INV-7 total 42000 for PO-1001"):
    return {"from_email": "sales@acme.com", "subject": f"RE: [OA-{CASE}] Purchase Order PO-1001", "body": body}


def _stub_mail(monkeypatch, stage="po_issued", po_vendor="v1"):
    seen = SimpleNamespace(events=[], invoiced=[], acks=[])
    monkeypatch.setattr(case_pipeline.operations_agent, "get_case_status", lambda cid: {"stage": stage})
    monkeypatch.setattr(case_pipeline.vendor_agent, "find_invited_vendor_id", lambda cid, email: "v1")
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "find_purchase_order",
                        lambda cid: {**PO, "vendor_id": po_vendor})
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event",
                        lambda cid, t, **kw: seen.events.append(t))
    monkeypatch.setattr(case_pipeline, "process_invoice",
                        lambda cid, body, source: seen.invoiced.append((cid, source)) or {"status": "matched"})
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "acknowledge", lambda cid, **how: seen.acks.append(how) or True)
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "classify_reply", lambda text: {"kind": "other", "issue": None})
    return seen


@pytest.mark.parametrize("stage", ["po_issued", "delivery_late", "delivered"])
def test_a_vendor_email_after_the_order_is_read_as_an_invoice(monkeypatch, stage):
    seen = _stub_mail(monkeypatch, stage=stage)
    assert case_pipeline.ingest_quote_email(_mail()) == "invoiced"
    assert seen.invoiced == [(CASE, "email")]


def test_a_reply_that_is_neither_an_invoice_nor_a_confirmation_is_only_logged(monkeypatch):
    seen = _stub_mail(monkeypatch)

    def not_invoice(cid, body, source):
        raise NotAnInvoice()

    monkeypatch.setattr(case_pipeline, "process_invoice", not_invoice)
    assert case_pipeline.ingest_quote_email(_mail("What is the delivery address?")) == "vendor_reply"
    assert seen.events == ["vendor.replied"] and seen.acks == []


def test_an_invoice_from_a_vendor_who_does_not_hold_the_order_is_ignored(monkeypatch):
    seen = _stub_mail(monkeypatch, po_vendor="someone-else")
    assert case_pipeline.ingest_quote_email(_mail()) == "not_accepting"
    assert seen.invoiced == [] and seen.events == ["quote.email_ignored"]


def test_a_quoted_only_reply_is_ignored(monkeypatch):
    seen = _stub_mail(monkeypatch)
    assert case_pipeline.ingest_quote_email(_mail("> quoted text only")) == "empty"
    assert seen.invoiced == []


# ---------- permissions over HTTP ----------

client = TestClient(app)


@pytest.fixture
def people(monkeypatch):
    users = {
        "alice": SimpleNamespace(user_id="alice", username="alice@x.co", role="user", is_active=True),
        "mgr": SimpleNamespace(user_id="mgr", username="mgr@x.co", role="manager", is_active=True),
        "view": SimpleNamespace(user_id="view", username="view@x.co", role="viewer", is_active=True),
    }
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {
        "admin": set(), "manager": set(DEFAULT_ROLE_PERMISSIONS["manager"]),
        "viewer": set(DEFAULT_ROLE_PERMISSIONS["viewer"]), "user": set(DEFAULT_ROLE_PERMISSIONS["user"])})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: users.get(uid.lower()))
    monkeypatch.setattr("app.api.deps.audit.record", lambda *a, **k: None)
    monkeypatch.setattr("app.controllers.invoice_controller.audit.record", lambda *a, **k: None)
    monkeypatch.setattr(invoice_agent, "list_invoices", lambda status=None: [])
    # who confirmed the goods for this order (an invoice may not be decided by that same person)
    from app.controllers import invoice_controller
    monkeypatch.setattr(invoice_controller.invoice_agent, "get_invoice", lambda iid: {"case_id": CASE})
    monkeypatch.setattr(invoice_controller.delivery_agent, "get_delivery", lambda cid: {"received_by": "clerk@x.co"})
    access.invalidate()
    yield
    access.invalidate()


def as_(uid, role):
    token, _ = security.create_access_token(uid, f"{uid}@x.co", role)
    return {"Authorization": f"Bearer {token}"}


def test_requesters_cannot_see_or_touch_invoices(people):
    for method, path in [("get", "/invoices"), ("get", f"/cases/{CASE}/invoices"),
                         ("post", f"/cases/{CASE}/invoices"), ("post", "/invoices/i1/approve"),
                         ("post", "/invoices/i1/reject")]:
        assert client.request(method.upper(), path, headers=as_("alice", "user"), json={"raw_text": "x"}).status_code == 403


def test_viewers_can_read_but_not_decide(people):
    assert client.get("/invoices", headers=as_("view", "viewer")).status_code == 200
    assert client.post("/invoices/i1/approve", headers=as_("view", "viewer"), json={}).status_code == 403


def test_managers_decide_under_their_own_name(people, monkeypatch):
    calls = []
    monkeypatch.setattr(case_pipeline, "decide_invoice",
                        lambda iid, approve, by, note: calls.append((iid, approve, by, note)) or {
                            "invoice_id": iid, "case_id": CASE, "purchase_order_id": "po", "vendor_id": "v1",
                            "vendor_name": "Acme", "po_number": "PO-1001", "invoice_number": "INV-7",
                            "total_amount": 1.0, "status": "approved", "issues": [], "source": "email",
                            "decided_by": by, "decision_note": note, "created_at": "2026-10-01T00:00:00",
                            "decided_at": None})
    r = client.post("/invoices/i1/approve", headers=as_("mgr", "manager"), json={"note": "ok", "decided_by": "ceo"})
    assert r.status_code == 200 and calls == [("i1", True, "mgr@x.co", "ok")]


def test_whoever_confirmed_the_goods_cannot_decide_that_invoice(people, monkeypatch):
    from app.controllers import invoice_controller
    monkeypatch.setattr(invoice_controller.delivery_agent, "get_delivery", lambda cid: {"received_by": "mgr@x.co"})
    monkeypatch.setattr(case_pipeline, "decide_invoice", lambda *a: pytest.fail("must not decide"))
    r = client.post("/invoices/i1/approve", headers=as_("mgr", "manager"), json={})
    assert r.status_code == 409 and "confirmed the goods" in r.json()["detail"]


def test_an_invoice_for_goods_nobody_has_confirmed_can_still_be_decided(people, monkeypatch):
    from app.controllers import invoice_controller
    from app.core.exceptions import PurchaseOrderNotFound

    def no_order(cid):
        raise PurchaseOrderNotFound(cid)
    monkeypatch.setattr(invoice_controller.delivery_agent, "get_delivery", no_order)
    monkeypatch.setattr(case_pipeline, "decide_invoice", lambda iid, approve, by, note: {
        "invoice_id": iid, "case_id": CASE, "purchase_order_id": "po", "vendor_id": "v1", "vendor_name": "Acme", "po_number": "PO-1",
        "invoice_number": "INV-9", "total_amount": 1.0, "status": "approved", "issues": [], "source": "email",
        "decided_by": by, "decision_note": note, "created_at": "2026-10-01T00:00:00", "decided_at": None})
    assert client.post("/invoices/i1/approve", headers=as_("mgr", "manager"), json={}).status_code == 200
