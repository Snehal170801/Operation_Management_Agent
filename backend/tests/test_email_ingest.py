import os

for key, value in {
    "SQL_SERVER": "test",
    "SQL_DATABASE": "test",
    "SQL_DRIVER": "test",
    "SQL_TRUSTED_CONNECTION": "yes",
    "JWT_SECRET": "test-secret",
}.items():
    os.environ.setdefault(key, value)

from app.core.email_parsing import clean_reply_body, make_subject, parse_case_ref  # noqa: E402
from app.core.exceptions import CaseNotFound  # noqa: E402
from app.orchestrator import case_pipeline  # noqa: E402

CASE_ID = "3f2b8c1a-1111-4222-8333-444455556666"


def test_subject_round_trips_even_after_reply_prefixes():
    assert parse_case_ref(make_subject(CASE_ID)) == CASE_ID
    assert parse_case_ref("RE: Fwd: " + make_subject(CASE_ID)) == CASE_ID


def test_unrelated_subject_has_no_case():
    assert parse_case_ref("Lunch tomorrow?") is None
    assert parse_case_ref("") is None


def test_reply_body_drops_quoted_text():
    body = (
        "Total Rs 42,000, delivery 7 days, 50% advance.\n\n"
        "On Mon, 5 Oct 2026, Ops <ops@x.com> wrote:\n"
        "> Please send us your quotation\n> for 50 cameras"
    )
    assert clean_reply_body(body) == "Total Rs 42,000, delivery 7 days, 50% advance."


def test_reply_body_drops_original_message_block():
    assert clean_reply_body("Price 100\n-----Original Message-----\nold stuff") == "Price 100"


def _stub(monkeypatch, stage="awaiting_quotes", vendor_id="v1", case_exists=True):
    submitted, events, advanced = [], [], []

    def get_case_status(cid):
        if not case_exists:
            raise CaseNotFound(cid)
        return {"stage": stage}

    monkeypatch.setattr(case_pipeline.operations_agent, "get_case_status", get_case_status)
    monkeypatch.setattr(case_pipeline.operations_agent, "publish_event",
                        lambda cid, t, **kw: events.append(t))
    monkeypatch.setattr(case_pipeline.vendor_agent, "find_invited_vendor_id",
                        lambda cid, email: vendor_id)
    monkeypatch.setattr(case_pipeline.vendor_agent, "submit_quote",
                        lambda cid, vid, text: submitted.append((cid, vid, text)))
    monkeypatch.setattr(case_pipeline, "advance_sourcing", lambda cid: advanced.append(cid))
    return submitted, events, advanced


def _msg(body="Total 42000, 7 days", subject=None):
    return {"from_email": "sales@vendor.com", "subject": subject or make_subject(CASE_ID), "body": body}


def test_valid_reply_becomes_a_quote_and_triggers_a_check(monkeypatch):
    submitted, events, advanced = _stub(monkeypatch)
    assert case_pipeline.ingest_quote_email(_msg()) == "quoted"
    assert submitted == [(CASE_ID, "v1", "Total 42000, 7 days")]
    assert advanced == [CASE_ID]


def test_untagged_email_is_ignored(monkeypatch):
    submitted, _, _ = _stub(monkeypatch)
    assert case_pipeline.ingest_quote_email(_msg(subject="hello")) == "no_case"
    assert submitted == []


def test_unknown_case_is_ignored(monkeypatch):
    submitted, _, _ = _stub(monkeypatch, case_exists=False)
    assert case_pipeline.ingest_quote_email(_msg()) == "no_case"
    assert submitted == []


def test_uninvited_sender_is_not_trusted(monkeypatch):
    submitted, events, _ = _stub(monkeypatch, vendor_id=None)
    assert case_pipeline.ingest_quote_email(_msg()) == "not_invited"
    assert submitted == [] and events == ["quote.email_ignored"]


def test_late_reply_after_ranking_is_ignored(monkeypatch):
    submitted, events, _ = _stub(monkeypatch, stage="vendor_selected")
    assert case_pipeline.ingest_quote_email(_msg()) == "not_accepting"
    assert submitted == [] and events == ["quote.email_ignored"]


def test_empty_reply_is_ignored(monkeypatch):
    submitted, events, _ = _stub(monkeypatch)
    assert case_pipeline.ingest_quote_email(_msg(body="> only quoted text")) == "empty"
    assert submitted == [] and events == ["quote.email_ignored", "document.unreadable"]     # and the team and the supplier are told (see test_pdf_intake.py)
