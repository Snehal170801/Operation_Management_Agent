"""The live "reading..." status of a supplier's document: received -> reading -> matched / needs a person; a failed read never leaves it on
'reading'; requesters see only the sanitised type."""

from datetime import datetime, timedelta

import pytest

from app.core import case_access, document_status as ds
from app.models.auth_schemas import CurrentUser
from app.orchestrator import case_pipeline

from .fake_world import now, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

T0 = datetime(2026, 10, 8, 10, 0)


def ev(kind, **payload):
    return {"event_type": kind, "payload": payload, "created_at": T0}


# ---- the rule -----------------------------------------------------------------------------------------------------------------------------

def test_the_status_follows_the_latest_document_event():
    assert ds.current([]) is None and ds.current([ev("case.created")]) is None
    assert ds.current([ev(ds.RECEIVED, files=["q.pdf"])])["state"] == "reading"
    assert ds.current([ev(ds.RECEIVED), ev(ds.READING, files=["q.pdf"])], T0)["files"] == ["q.pdf"]
    assert ds.current([ev(ds.READING), ev(ds.READ, outcome="matched")])["state"] == "matched"
    assert ds.current([ev(ds.READING), ev(ds.READ, outcome="needs_person", reason="x")]) == {"state": "needs_person", "files": [], "reason": "x"}
    assert ds.current([ev(ds.READ, outcome="weird")])["state"] == "needs_person"                          # an unknown outcome is never shown as fine


def test_a_second_document_replaces_the_first():
    events = [ev(ds.READ, outcome="matched"), ev(ds.RECEIVED, files=["b.pdf"]), ev(ds.READING)]
    assert ds.current(events)["state"] == "reading"


def test_reading_that_never_finishes_turns_into_needs_a_person():
    old = dict(ev(ds.READING), created_at=T0 - timedelta(seconds=ds.STUCK_AFTER_SECONDS + 5))
    assert ds.current([old], T0)["state"] == "needs_person" and ds.current([dict(old, created_at=T0)], T0)["state"] == "reading"


# ---- through the pipeline -----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    return standard_world(monkeypatch)


def doc_events(w, case_id):
    return [e for e in w.events[case_id] if e.event_type.startswith("document.")]


def test_a_pdf_quote_goes_received_reading_read_matched(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "", attachments=[{"name": "quote.pdf", "text": QUOTE_42K}])
    assert [e.event_type for e in doc_events(w, case_id)] == ["document.received", "document.reading", "document.read"]
    last = doc_events(w, case_id)[-1].payload
    assert last["outcome"] == "matched" and last["files"] == ["quote.pdf"]


def test_a_plain_email_with_no_attachment_shows_no_document_status(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", QUOTE_42K)
    assert doc_events(w, case_id) == []


def test_a_failed_read_says_needs_a_person_tells_the_team_and_still_raises(w, monkeypatch):
    case_id = w.submit("50 cameras")

    def boom(*a, **k):
        raise RuntimeError("AI down")
    monkeypatch.setattr(case_pipeline.vendor_agent, "submit_quote", boom)
    with pytest.raises(RuntimeError):
        w.reply(case_id, "Acme", "", attachments=[{"name": "quote.pdf", "text": QUOTE_42K}])
    events = doc_events(w, case_id)
    assert [e.event_type for e in events][-1] == "document.read" and events[-1].payload["outcome"] == "needs_person"
    assert "Reading failed" in events[-1].payload["reason"] and w.emails_to("manager@x.co")
    assert ds.current([{"event_type": e.event_type, "payload": e.payload, "created_at": e.created_at} for e in events])["state"] == "needs_person"


def test_a_failing_status_write_never_breaks_the_real_work(w, monkeypatch):
    case_id = w.submit("50 cameras")
    real = case_pipeline.operations_agent.publish_event

    def flaky(cid, kind, *a, **k):
        if kind.startswith("document."):
            raise RuntimeError("db hiccup")
        return real(cid, kind, *a, **k)
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event", flaky)
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "quote.pdf", "text": QUOTE_42K}]) == "quoted"


def test_an_unreadable_file_ends_as_needs_a_person(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "", attachments=[{"name": "locked.pdf", "text": ""}])
    reads = [e for e in doc_events(w, case_id) if e.event_type == "document.read"]
    assert len(reads) == 1 and reads[0].payload["outcome"] == "needs_person" and "document.unreadable" in w.event_types(case_id)


def test_an_invoice_that_matches_reads_as_matched_and_one_that_does_not_needs_a_person(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    po = w.pos[case_id]
    good = f"TAX INVOICE\nInvoice No. INV-1\nPO-{po.po_number}\nTotal 99999999"
    w.reply(case_id, "Acme", "", attachments=[{"name": "inv.pdf", "text": good}])
    assert doc_events(w, case_id)[-1].payload["outcome"] in ("matched", "needs_person")


# ---- who sees it ----------------------------------------------------------------------------------------------------------------------------

def test_a_requester_sees_the_document_steps_by_type_only_and_never_the_names_or_reason(monkeypatch):
    monkeypatch.setattr(case_access.access, "has_permission", lambda role, permission: False)
    events = [{"event_type": t, "payload": {"files": ["secret-quote.pdf"], "reason": "x"}} for t in ("document.received", "document.reading", "document.read", "document.unreadable")]
    seen = case_access.visible_events(events, CurrentUser(user_id="9", username="ravi", role="u_requester"))
    assert [e["event_type"] for e in seen] == ["document.received", "document.reading", "document.read"] and all(e["payload"] is None for e in seen)
