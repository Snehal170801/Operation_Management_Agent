"""'Please check your email' calls: after we email a vendor, ring them and say so in Hindi / Marathi / English."""

import urllib.parse
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents import calling_agent
from app.clients import twilio_client
from app.core.config import settings
from app.models.vendor_schemas import UpsertVendorRequest

CASE = "case-1"
IST = calling_agent._IST


def vendor(name, phone, language="hi", vid=None):
    return SimpleNamespace(vendor_id=vid or name, name=name, phone=phone, call_language=language)


@pytest.fixture
def world(monkeypatch):
    w = SimpleNamespace(vendors=[], events=[], calls=[], paused=False, hour_ok=True, refuse=None)
    monkeypatch.setattr(settings, "CALL_AFTER_EMAIL", True)
    monkeypatch.setattr(settings, "CALL_PROVIDER", "twilio")
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "ACx")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "t")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15005550006")
    monkeypatch.setattr(settings, "TWILIO_ANSWER_URL", "")  # a paid account
    monkeypatch.setattr(settings, "CALL_ALLOWED_NUMBERS", [])
    monkeypatch.setattr(settings, "CALL_COMPANY_NAME", "Cognexa")
    monkeypatch.setattr(calling_agent.vendor_repository, "find_all_vendors", lambda: w.vendors)
    monkeypatch.setattr(calling_agent.automation, "is_paused", lambda: w.paused)
    monkeypatch.setattr(calling_agent, "_within_calling_hours", lambda now=None: w.hour_ok)
    monkeypatch.setattr(calling_agent.operations_agent, "get_case_events", lambda cid: list(w.events))
    monkeypatch.setattr(
        calling_agent.operations_agent, "publish_event",
        lambda cid, t, agent_name=None, payload=None: w.events.append({"event_type": t, "payload": payload}),
    )

    def place(to, text, language, voice):
        if w.refuse:
            raise RuntimeError(w.refuse)
        w.calls.append(SimpleNamespace(to=to, text=text, language=language, voice=voice))
        return f"CA{len(w.calls):032d}"

    monkeypatch.setattr(twilio_client, "place_message_call", place)
    return w


def reasons(w):
    return [e["payload"]["reason"] for e in w.events if e["event_type"] == "call.skipped"]


def test_calls_each_vendor_in_their_own_language(world):
    world.vendors = [vendor("Acme", "+919000000001", "hi"), vendor("Bharat", "+919000000002", "mr"), vendor("Cargo", "+919000000003", "en")]
    assert calling_agent.notify_email_sent(CASE, ["Acme", "Bharat", "Cargo"], "rfq") == ["Acme", "Bharat", "Cargo"]
    by = {c.to: c for c in world.calls}
    assert by["+919000000001"].language == "hi-IN" and "कृपया अपना ईमेल देखिए" in by["+919000000001"].text
    assert by["+919000000002"].language == "mr-IN" and "कृपया तुमचा ईमेल तपासा" in by["+919000000002"].text
    assert by["+919000000003"].language == "en-IN" and "Please check your email" in by["+919000000003"].text
    assert "Cognexa" in by["+919000000001"].text
    assert by["+919000000002"].voice == "Google.mr-IN-Chirp3-HD-Aoede"  # Marathi is only offered through Google voices
    assert [e["payload"]["language"] for e in world.events if e["event_type"] == "call.notified"] == ["hi", "mr", "en"]


def test_a_purchase_order_call_says_so(world):
    world.vendors = [vendor("Acme", "+919000000001", "hi")]
    calling_agent.notify_email_sent(CASE, ["Acme"], "po")
    assert "खरीद आदेश" in world.calls[0].text


def test_only_the_vendors_that_were_just_emailed_are_called(world):
    world.vendors = [vendor("Acme", "+919000000001"), vendor("Other", "+919000000002")]
    assert calling_agent.notify_email_sent(CASE, ["acme"], "rfq") == ["Acme"]  # case-insensitive; Other was not emailed
    assert [c.to for c in world.calls] == ["+919000000001"]


def test_a_vendor_without_a_phone_is_just_not_called(world):
    world.vendors = [vendor("Acme", None)]
    assert calling_agent.notify_email_sent(CASE, ["Acme"], "rfq") == []
    assert world.calls == [] and reasons(world) == []


def test_the_same_vendor_is_not_rung_twice_for_the_same_thing(world):
    world.vendors = [vendor("Acme", "+919000000001")]
    calling_agent.notify_email_sent(CASE, ["Acme"], "rfq")
    calling_agent.notify_email_sent(CASE, ["Acme"], "rfq")  # e.g. a retry
    assert len(world.calls) == 1
    calling_agent.notify_email_sent(CASE, ["Acme"], "po")  # a different thing: allowed
    assert len(world.calls) == 2


def test_off_by_default_and_when_switched_off(world, monkeypatch):
    world.vendors = [vendor("Acme", "+919000000001")]
    monkeypatch.setattr(settings, "CALL_AFTER_EMAIL", False)
    assert calling_agent.notify_email_sent(CASE, ["Acme"], "rfq") == [] and world.calls == [] and world.events == []


@pytest.mark.parametrize("flag,expected", [("paused", "automation is paused"), ("hour_ok", "outside calling hours")])
def test_skips_with_a_reason_on_the_case_timeline(world, flag, expected):
    world.vendors = [vendor("Acme", "+919000000001")]
    setattr(world, flag, flag == "paused")  # paused -> True; hour_ok -> False
    assert calling_agent.notify_email_sent(CASE, ["Acme"], "rfq") == []
    assert world.calls == [] and expected in reasons(world)[0]


def test_a_free_trial_cannot_speak_custom_text_so_it_skips_and_says_why(world, monkeypatch):
    world.vendors = [vendor("Acme", "+919000000001")]
    monkeypatch.setattr(settings, "TWILIO_ANSWER_URL", "https://webhooks.twilio.com/v1/Voice/Template/voice_auto_response")
    assert calling_agent.notify_email_sent(CASE, ["Acme"], "rfq") == []
    assert "paid Twilio account" in reasons(world)[0]


def test_the_allowed_numbers_list_still_applies(world, monkeypatch):
    world.vendors = [vendor("Acme", "+919000000001"), vendor("Bharat", "+919000000002")]
    monkeypatch.setattr(settings, "CALL_ALLOWED_NUMBERS", ["+919000000002"])
    assert calling_agent.notify_email_sent(CASE, ["Acme", "Bharat"], "rfq") == ["Bharat"]
    assert "not on the allowed list" in reasons(world)[0]


def test_a_refused_call_is_noted_and_never_breaks_the_case(world):
    world.vendors = [vendor("Acme", "+919000000001")]
    world.refuse = "Permission to call this region is not enabled"
    assert calling_agent.notify_email_sent(CASE, ["Acme"], "rfq") == []
    assert "Permission to call this region" in reasons(world)[0]


def test_an_unexpected_crash_is_swallowed(world, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(calling_agent.vendor_repository, "find_all_vendors", boom)
    assert calling_agent.notify_email_sent(CASE, ["Acme"], "rfq") == []


def test_calling_hours_are_india_time(monkeypatch):
    monkeypatch.setattr(settings, "CALL_HOURS_START", 9)
    monkeypatch.setattr(settings, "CALL_HOURS_END", 19)
    assert calling_agent._within_calling_hours(datetime(2026, 10, 3, 12, 0, tzinfo=IST))
    assert not calling_agent._within_calling_hours(datetime(2026, 10, 3, 22, 30, tzinfo=IST))
    assert not calling_agent._within_calling_hours(datetime(2026, 10, 3, 8, 59, tzinfo=IST))
    # 06:00 UTC is 11:30 in India: inside the window even though it looks early in UTC
    assert calling_agent._within_calling_hours(datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc))


def test_the_call_instructions_use_the_language_and_voice_and_are_escaped(monkeypatch):
    seen = {}

    class Reply:
        def read(self):
            return b'{"sid": "CA1"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(request, timeout=0):
        seen.update(dict(urllib.parse.parse_qsl(request.data.decode())))
        return Reply()

    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "ACx")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "t")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15005550006")
    monkeypatch.setattr(twilio_client.urllib.request, "urlopen", fake)
    assert twilio_client.place_message_call("+919000000001", "A & B <x>", "mr-IN", "Google.mr-IN-Chirp3-HD-Aoede") == "CA1"
    assert 'language="mr-IN"' in seen["Twiml"] and 'voice="Google.mr-IN-Chirp3-HD-Aoede"' in seen["Twiml"]
    assert "A &amp; B &lt;x&gt;" in seen["Twiml"] and seen["Twiml"].endswith("<Hangup/></Response>")


def test_vendor_phone_must_include_a_country_code_and_language_must_be_known():
    assert UpsertVendorRequest(name="A", phone="+919000000001", call_language="mr").call_language == "mr"
    for bad in ("9000000001", "+91 90000 00001", "abc"):
        with pytest.raises(ValidationError):
            UpsertVendorRequest(name="A", phone=bad)
    with pytest.raises(ValidationError):
        UpsertVendorRequest(name="A", call_language="fr")
