import os

for key, value in {
    "SQL_SERVER": "test",
    "SQL_DATABASE": "test",
    "SQL_DRIVER": "test",
    "SQL_TRUSTED_CONNECTION": "yes",
}.items():
    os.environ.setdefault(key, value)

from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from app.agents import approval_agent  # noqa: E402
from app.core.approval_policy import human_review_reasons  # noqa: E402
from app.core.exceptions import ApprovalAlreadyDecided  # noqa: E402


def test_routine_selection_is_auto_approved():
    assert human_review_reasons({"price": 10000.0}, 4.5, quote_count=3) == []


@pytest.mark.parametrize("quote,reliability,count", [
    ({"price": 90000.0}, 4.5, 3),   # over amount limit
    ({"price": None}, 4.5, 3),      # unreadable price
    ({"price": 10000.0}, 3.0, 3),   # unreliable vendor
    ({"price": 10000.0}, None, 3),  # unknown vendor
    ({"price": 10000.0}, 4.5, 1),   # single quote
    (None, 4.5, 3),                 # no quote for selected vendor
])
def test_exceptions_need_a_human(quote, reliability, count):
    assert human_review_reasons(quote, reliability, count)


def _stub_case(monkeypatch, quote_price, reliability, quote_count):
    events, stages = [], []
    monkeypatch.setattr(approval_agent.vendor_agent, "get_vendor_selection",
                        lambda cid: {"vendor_id": "v1"})
    monkeypatch.setattr(approval_agent.vendor_agent, "get_quotes",
                        lambda cid: [{"vendor_id": "v1", "price": quote_price}] + [{"vendor_id": f"other{i}", "price": quote_price} for i in range(quote_count - 1)])
    monkeypatch.setattr(approval_agent.vendor_agent, "get_all_vendors",
                        lambda: [{"vendor_id": "v1", "reliability_score": reliability}])
    monkeypatch.setattr(approval_agent.operations_agent, "publish_event",
                        lambda cid, t, **kw: events.append(t))
    monkeypatch.setattr(approval_agent.operations_agent, "set_stage",
                        lambda cid, s: stages.append(s))
    inserted = {}
    monkeypatch.setattr(approval_agent.approval_repository, "supersede_pending", lambda *a: None)
    monkeypatch.setattr(approval_agent.approval_repository, "insert_approval",
                        lambda aid, cid, t, status, reasons, decided_by=None:
                        inserted.update(id=aid, case_id=cid, status=status, reasons=reasons))
    monkeypatch.setattr(approval_agent, "get_approval", lambda aid: dict(inserted))
    return events, stages, inserted


def test_routine_case_auto_approves_without_human(monkeypatch):
    events, stages, inserted = _stub_case(monkeypatch, 10000.0, 4.5, 3)
    approval_agent.review_vendor_selection("c1")
    assert inserted["status"] == "auto_approved"
    assert stages == ["approved"]
    assert events == ["approval.auto_approved"]


def test_exception_case_waits_for_human(monkeypatch):
    events, stages, inserted = _stub_case(monkeypatch, 90000.0, 4.5, 3)
    approval_agent.review_vendor_selection("c1")
    assert inserted["status"] == "pending"
    assert stages == ["awaiting_approval"]
    assert events == ["approval.requested"]


def test_reject_closes_case_and_double_decision_conflicts(monkeypatch):
    events, closed = [], []
    row = {"approval_id": "a1", "case_id": "c1"}
    monkeypatch.setattr(approval_agent, "get_approval", lambda aid: row)
    monkeypatch.setattr(approval_agent.operations_agent, "publish_event",
                        lambda cid, t, **kw: events.append(t))
    monkeypatch.setattr(approval_agent.operations_agent, "close_case",
                        lambda cid, stage, reason: closed.append(stage))

    monkeypatch.setattr(approval_agent.approval_repository, "decide_pending", lambda *a: True)
    approval_agent.decide("a1", False, "shri", "too expensive")
    assert closed == ["rejected"] and events == ["approval.rejected"]

    monkeypatch.setattr(approval_agent.approval_repository, "decide_pending", lambda *a: False)
    with pytest.raises(ApprovalAlreadyDecided):
        approval_agent.decide("a1", True, "shri", None)
