"""The same attachment is never sent to the AI twice: it is fingerprinted by content, remembered per case once handled, and a repeat is
noted on the case."""

import pytest

from app.agents import document_agent
from app.core import file_hash as fh
from app.orchestrator import case_pipeline

from .fake_world import standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K

PDF = {"name": "quote.pdf", "text": QUOTE_42K}


# ---- the rule ---------------------------------------------------------------------------------------------------------------------------

def test_the_fingerprint_follows_the_content_not_the_name():
    assert fh.fingerprint(PDF) == fh.fingerprint({"name": "renamed.pdf", "text": "  " + QUOTE_42K + "\n"})
    assert fh.fingerprint(PDF) != fh.fingerprint({"name": "quote.pdf", "text": QUOTE_45K})
    assert fh.fingerprint({"name": "scan.pdf", "images": ["aaa"]}) != fh.fingerprint({"name": "scan.pdf", "images": ["bbb"]})
    assert fh.fingerprint({"name": "x", "sha256": "ABC"}) == "abc"


def test_a_file_with_nothing_readable_has_no_fingerprint_and_is_left_for_the_unreadable_rule():
    assert fh.fingerprint({"name": "locked.pdf", "text": "  "}) is None and fh.fingerprint({"name": "x"}) is None
    fresh, repeated, remember = fh.split([{"name": "locked.pdf", "text": ""}], {"anything"})
    assert fresh and not repeated and remember == []


def test_split_separates_new_known_and_in_email_copies():
    known = {fh.fingerprint(PDF)}
    other = {"name": "b.pdf", "text": QUOTE_45K}
    fresh, repeated, remember = fh.split([PDF, other, dict(other, name="copy.pdf")], known)
    assert [a["name"] for a in fresh] == ["b.pdf"] and [a["name"] for a in repeated] == ["quote.pdf", "copy.pdf"]
    assert remember == [(fh.fingerprint(other), "b.pdf")]


# ---- through the pipeline -----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    return standard_world(monkeypatch)


def count_ai_reads(w, monkeypatch):
    calls = []
    real = w._fake_ai
    monkeypatch.setattr(case_pipeline.vendor_agent.azure_openai_client, "ask_json", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    return calls


def test_the_same_pdf_sent_twice_is_read_once_and_the_repeat_is_noted(w, monkeypatch):
    case_id = w.submit("50 cameras")
    calls = count_ai_reads(w, monkeypatch)
    assert w.reply(case_id, "Acme", "", attachments=[PDF]) == "quoted"
    reads = len(calls)
    assert reads >= 1 and len([q for q in w.quotes if q.case_id == case_id]) == 1
    assert w.reply(case_id, "Acme", "", attachments=[dict(PDF, name="again.pdf")]) == "duplicate_file"
    assert len(calls) == reads and len([q for q in w.quotes if q.case_id == case_id]) == 1
    assert "document.duplicate_file" in w.event_types(case_id)


def test_a_repeated_file_with_new_words_in_the_email_still_reads_the_words(w, monkeypatch):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "", attachments=[PDF])
    assert w.reply(case_id, "Acme", "Sorry, we are unable to supply these.", attachments=[PDF]) == "declined"
    assert "document.duplicate_file" in w.event_types(case_id)


def test_a_new_file_from_the_same_supplier_is_read(w):
    case_id = w.submit("50 cameras")
    w.reply(case_id, "Acme", "", attachments=[PDF])
    assert w.reply(case_id, "Acme", "", attachments=[{"name": "revised.pdf", "text": QUOTE_45K}]) != "duplicate_file"


def test_the_same_file_on_another_case_is_read_again_files_are_remembered_per_case(w):
    first, second = w.submit("50 cameras"), w.submit("50 cameras")
    w.reply(first, "Acme", "", attachments=[PDF])
    assert w.reply(second, "Acme", "", attachments=[PDF]) == "quoted"


def test_a_file_is_remembered_only_after_it_was_handled(w, monkeypatch):
    case_id = w.submit("50 cameras")

    def crash(*a, **k):
        raise RuntimeError("AI down")
    monkeypatch.setattr(case_pipeline.vendor_agent, "submit_quote", crash)
    with pytest.raises(RuntimeError):
        w.reply(case_id, "Acme", "", attachments=[PDF])
    assert not w.read_files.get(case_id)                                       # so the mail can be read again when the AI is back
    monkeypatch.undo()


def test_a_failing_memory_never_blocks_a_new_quote(w, monkeypatch):
    case_id = w.submit("50 cameras")
    monkeypatch.setattr(document_agent.read_file_repo, "known_hashes", lambda c: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(document_agent.read_file_repo, "remember", lambda c, f: (_ for _ in ()).throw(RuntimeError("db down")))
    assert w.reply(case_id, "Acme", "", attachments=[PDF]) == "quoted"
