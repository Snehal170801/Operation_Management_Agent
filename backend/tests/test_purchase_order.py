import os

for key, value in {
    "SQL_SERVER": "test",
    "SQL_DATABASE": "test",
    "SQL_DRIVER": "test",
    "SQL_TRUSTED_CONNECTION": "yes",
    "JWT_SECRET": "test-secret",
}.items():
    os.environ.setdefault(key, value)

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402

from app.agents import purchase_order_agent  # noqa: E402
from app.core.exceptions import VendorNotApproved  # noqa: E402
from app.orchestrator import case_pipeline  # noqa: E402

CASE = "3f2b8c1a-1111-4222-8333-444455556666"
ITEMS = [{"description": "CCTV camera", "quantity": 50}]


def _po(status="sent"):
    return {
        "purchase_order_id": "po-id", "po_number": "PO-1001", "case_id": CASE, "vendor_id": "v1",
        "vendor_name": "Acme", "total_amount": 42000.0, "lead_time_days": 7, "terms": "50% advance",
        "expected_delivery_date": date(2026, 10, 20), "items": ITEMS, "status": status,
        "created_at": datetime(2026, 10, 1), "sent_at": None,
    }


# ---------- agent ----------

def _stub_agent(monkeypatch, po):
    sent, statuses, events = [], [], []
    monkeypatch.setattr(purchase_order_agent, "get_purchase_order", lambda cid: po)
    monkeypatch.setattr(purchase_order_agent.email_client, "send_email",
                        lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(purchase_order_agent.purchase_order_repository, "update_status",
                        lambda pid, status: statuses.append(status))
    monkeypatch.setattr(purchase_order_agent.operations_agent, "publish_event",
                        lambda cid, t, **kw: events.append(t))
    return sent, statuses, events


def test_po_email_has_the_agreed_details(monkeypatch):
    sent, statuses, events = _stub_agent(monkeypatch, _po())
    purchase_order_agent.resend(CASE, {"name": "Acme", "email": "sales@acme.com"})
    to, subject, body = sent[0]
    assert to == "sales@acme.com"
    # tagged with the case so the vendor's reply (e.g. an invoice) maps back to it
    assert subject == f"[OA-{CASE}] Purchase Order PO-1001"
    assert "CCTV camera x 50" in body and "42,000.00" in body and "20 Oct 2026" in body
    assert "50% advance" in body
    assert statuses == ["sent"] and events == ["po.issued"]


def test_vendor_without_email_leaves_po_unsent(monkeypatch):
    sent, statuses, events = _stub_agent(monkeypatch, _po())
    purchase_order_agent.resend(CASE, {"name": "Acme", "email": None})
    assert sent == [] and statuses == ["send_failed"] and events == ["po.send_failed"]


def test_smtp_failure_is_recorded_not_raised(monkeypatch):
    _, statuses, events = _stub_agent(monkeypatch, _po())

    def boom(*a):
        raise OSError("smtp down")

    monkeypatch.setattr(purchase_order_agent.email_client, "send_email", boom)
    purchase_order_agent.resend(CASE, {"name": "Acme", "email": "sales@acme.com"})
    assert statuses == ["send_failed"] and events == ["po.send_failed"]


# ---------- pipeline ----------

def _stub_pipeline(monkeypatch, approvals, existing_po=None, created_status="sent"):
    log = {"created": [], "resent": [], "stages": [], "alerts": []}
    monkeypatch.setattr(case_pipeline.approval_agent, "get_approvals",
                        lambda status=None, case_id=None: approvals)
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_vendor_selection",
                        lambda cid: {"vendor_id": "v1", "vendor_name": "Acme", "rationale": ""})
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_all_vendors",
                        lambda: [{"vendor_id": "v1", "name": "Acme", "email": "s@acme.com"}])
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_quotes", lambda cid: [
        {"vendor_id": "v1", "price": 50000.0, "lead_time_days": 9, "terms": "old"},
        {"vendor_id": "v1", "price": 42000.0, "lead_time_days": 7, "terms": "new"},
        {"vendor_id": "v2", "price": 10.0, "lead_time_days": 1, "terms": "other vendor"},
    ])
    monkeypatch.setattr(case_pipeline.purchase_agent, "get_purchase_request", lambda cid: {"items": ITEMS})
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "find_purchase_order", lambda cid: existing_po)
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "create_and_send",
                        lambda cid, vendor, quote, items:
                        log["created"].append((vendor["name"], quote, items)) or _po(created_status))
    monkeypatch.setattr(case_pipeline.purchase_order_agent, "resend",
                        lambda cid, vendor: log["resent"].append(cid) or _po("sent"))
    monkeypatch.setattr(case_pipeline.operations_agent, "set_stage", lambda cid, s: log["stages"].append(s))
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", lambda *a, **k: None)
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled",
                        lambda cid, reason, team=None: log["alerts"].append(reason))
    return log


def test_approved_case_gets_a_po_using_the_cheapest_quote_of_that_vendor(monkeypatch):
    log = _stub_pipeline(monkeypatch, [{"status": "approved"}])
    case_pipeline.issue_purchase_order(CASE)
    name, quote, items = log["created"][0]
    assert name == "Acme" and quote["price"] == 42000.0 and items == ITEMS
    assert log["stages"] == ["po_issued"] and log["alerts"] == []


def test_auto_approved_also_qualifies(monkeypatch):
    log = _stub_pipeline(monkeypatch, [{"status": "auto_approved"}])
    case_pipeline.issue_purchase_order(CASE)
    assert len(log["created"]) == 1


@pytest.mark.parametrize("status", ["pending", "rejected", "superseded"])
def test_unapproved_case_never_gets_a_po(monkeypatch, status):
    log = _stub_pipeline(monkeypatch, [{"status": status}])
    with pytest.raises(VendorNotApproved):
        case_pipeline.issue_purchase_order(CASE)
    assert log["created"] == []


def test_second_call_does_not_create_a_duplicate(monkeypatch):
    log = _stub_pipeline(monkeypatch, [{"status": "approved"}], existing_po=_po("sent"))
    assert case_pipeline.issue_purchase_order(CASE)["po_number"] == "PO-1001"
    assert log["created"] == [] and log["resent"] == []


def test_failed_send_is_retried_not_recreated(monkeypatch):
    log = _stub_pipeline(monkeypatch, [{"status": "approved"}], existing_po=_po("send_failed"))
    case_pipeline.issue_purchase_order(CASE)
    assert log["created"] == [] and log["resent"] == [CASE]
    assert log["stages"] == ["po_issued"]


def test_unsendable_po_alerts_a_human(monkeypatch):
    log = _stub_pipeline(monkeypatch, [{"status": "approved"}], created_status="send_failed")
    case_pipeline.issue_purchase_order(CASE)
    assert log["stages"] == ["po_send_failed"] and "PO-1001" in log["alerts"][0]


def test_auto_approval_flows_straight_into_a_po(monkeypatch):
    issued = []
    monkeypatch.setattr(case_pipeline.purchase_agent, "get_purchase_request", lambda cid: {"items": [], "needed_by": None, "urgent": False})
    monkeypatch.setattr(case_pipeline.vendor_agent, "rank_vendors", lambda cid, needed_by=None: None)
    monkeypatch.setattr(case_pipeline.approval_agent, "review_vendor_selection",
                        lambda cid, needed_by=None: {"status": "auto_approved", "reasons": []})
    monkeypatch.setattr(case_pipeline.vendor_agent, "get_vendor_selection",
                        lambda cid: {"vendor_name": "Acme", "rationale": ""})
    monkeypatch.setattr(case_pipeline, "issue_purchase_order", lambda cid: issued.append(cid))
    case_pipeline.rank_and_review(CASE)
    assert issued == [CASE]


def test_human_approval_issues_po_but_rejection_does_not(monkeypatch):
    issued = []
    monkeypatch.setattr(case_pipeline, "issue_purchase_order", lambda cid: issued.append(cid))
    monkeypatch.setattr(case_pipeline.approval_agent, "get_approval", lambda aid: {"case_id": CASE, "approval_type": "vendor_selection"})
    monkeypatch.setattr(case_pipeline.approval_agent, "decide",
                        lambda aid, approve, by, note, re_sourcing=False: {"case_id": CASE})
    case_pipeline.decide_approval("a1", True, "shri", None)
    case_pipeline.decide_approval("a2", False, "shri", "too dear")
    assert issued == [CASE]


def test_po_failure_never_undoes_the_approval(monkeypatch):
    stages, alerts = [], []

    def boom(cid):
        raise RuntimeError("db down")

    monkeypatch.setattr(case_pipeline, "issue_purchase_order", boom)
    monkeypatch.setattr(case_pipeline.approval_agent, "get_approval", lambda aid: {"case_id": CASE, "approval_type": "vendor_selection"})
    monkeypatch.setattr(case_pipeline.approval_agent, "decide",
                        lambda aid, approve, by, note, re_sourcing=False: {"case_id": CASE, "status": "approved"})
    monkeypatch.setattr(case_pipeline.operations_agent, "set_stage", lambda cid, s: stages.append(s))
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", lambda *a, **k: None)
    monkeypatch.setattr(case_pipeline.notification_agent, "notify_case_stalled",
                        lambda cid, reason, team=None: alerts.append(reason))

    result = case_pipeline.decide_approval("a1", True, "shri", None)  # must not raise
    assert result["status"] == "approved"
    assert stages == ["po_failed"] and "db down" in alerts[0]
