import base64
import io
import urllib.error
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app.agents import calling_agent
from app.clients import exotel_client
from app.core import access, security
from app.core.config import settings
from app.core.exceptions import InvalidInput
from app.main import app

client = TestClient(app)


@pytest.fixture
def exotel(monkeypatch):
    monkeypatch.setattr(settings, "CALL_PROVIDER", "exotel")
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", "acme1")
    monkeypatch.setattr(settings, "EXOTEL_API_KEY", "key123")
    monkeypatch.setattr(settings, "EXOTEL_API_TOKEN", "tok456")
    monkeypatch.setattr(settings, "EXOTEL_FROM_NUMBER", "09513886363")
    monkeypatch.setattr(settings, "EXOTEL_APP_ID", "12345")
    monkeypatch.setattr(settings, "EXOTEL_CONNECT_TO", "")
    monkeypatch.setattr(settings, "EXOTEL_HOST", "api.in.exotel.com")
    monkeypatch.setattr(settings, "EXOTEL_TIME_LIMIT", 0)
    monkeypatch.setattr(settings, "CALL_ALLOWED_NUMBERS", [])


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def capture_http(monkeypatch, body='{"Call": {"Sid": "c5797dcb"}}'):
    seen = {}

    def fake_urlopen(request, timeout=0):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["params"] = dict(urllib.parse.parse_qsl(request.data.decode()))
        return FakeResponse(body.encode())

    monkeypatch.setattr(exotel_client.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_not_configured_means_no_call_and_a_clear_message(monkeypatch):
    monkeypatch.setattr(settings, "CALL_PROVIDER", "exotel")
    monkeypatch.setattr(settings, "EXOTEL_ACCOUNT_SID", "")
    with pytest.raises(InvalidInput, match="isn't set up"):
        calling_agent.start_call("+919325642310", None)


def test_needs_a_flow_or_a_number_to_connect_to(exotel, monkeypatch):
    monkeypatch.setattr(settings, "EXOTEL_APP_ID", "")
    assert not exotel_client.is_configured()


def test_bad_numbers_and_allowlist(exotel, monkeypatch):
    for bad in ("9325642310", "+0123456789", "call me", "+91 93256 42310"):
        with pytest.raises(InvalidInput, match="country code"):
            calling_agent.start_call(bad, None)
    monkeypatch.setattr(settings, "CALL_ALLOWED_NUMBERS", ["+919325642310"])
    with pytest.raises(InvalidInput, match="allowed list"):
        calling_agent.start_call("+919000000001", None)


def test_request_to_a_flow_is_built_the_way_exotel_documents(exotel, monkeypatch):
    seen = capture_http(monkeypatch)
    assert exotel_client.place_call("+919325642310") == "c5797dcb"
    assert seen["url"] == "https://api.in.exotel.com/v1/Accounts/acme1/Calls/connect"
    assert seen["auth"] == "Basic " + base64.b64encode(b"key123:tok456").decode()
    assert seen["params"] == {
        "From": "+919325642310", "CallerId": "09513886363", "CallType": "trans", "TimeOut": "30",
        "Url": "http://my.exotel.in/exoml/start/12345",
    }


def test_the_call_is_cut_after_the_time_limit_when_one_is_set(exotel, monkeypatch):
    seen = capture_http(monkeypatch)
    monkeypatch.setattr(settings, "EXOTEL_TIME_LIMIT", 0)
    exotel_client.place_call("+919325642310")
    assert "TimeLimit" not in seen["params"]
    monkeypatch.setattr(settings, "EXOTEL_TIME_LIMIT", 3)
    exotel_client.place_call("+919325642310")
    assert seen["params"]["TimeLimit"] == "3"


def test_request_connecting_to_a_second_number(exotel, monkeypatch):
    monkeypatch.setattr(settings, "EXOTEL_APP_ID", "")
    monkeypatch.setattr(settings, "EXOTEL_CONNECT_TO", "09000000000")
    seen = capture_http(monkeypatch)
    exotel_client.place_call("+919325642310")
    assert seen["params"]["To"] == "09000000000" and "Url" not in seen["params"]


def test_the_call_id_is_read_from_json_or_xml(exotel, monkeypatch):
    capture_http(monkeypatch, "<TwilioResponse><Call><Sid>abc999</Sid><Status>in-progress</Status></Call></TwilioResponse>")
    assert exotel_client.place_call("+919325642310") == "abc999"
    capture_http(monkeypatch, "not a call")
    with pytest.raises(RuntimeError, match="no call id"):
        exotel_client.place_call("+919325642310")


def test_exotels_refusal_is_shown_as_a_clear_message_not_a_server_error(exotel, monkeypatch):
    def refuse(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(
            b"<RestException><Message>Account is not verified.</Message></RestException>"))

    monkeypatch.setattr(exotel_client.urllib.request, "urlopen", refuse)
    with pytest.raises(InvalidInput, match="Account is not verified"):
        calling_agent.start_call("+919325642310", None)

    def unreachable(request, timeout=0):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(exotel_client.urllib.request, "urlopen", unreachable)
    with pytest.raises(InvalidInput, match="Could not reach Exotel"):
        calling_agent.start_call("+919325642310", None)


def test_a_started_call_is_noted_on_the_case(exotel, monkeypatch):
    capture_http(monkeypatch)
    saved = []
    monkeypatch.setattr(calling_agent.operations_agent, "publish_event",
                        lambda cid, t, agent_name=None, payload=None: saved.append((cid, t, payload)))
    out = calling_agent.start_call("+919325642310", "CASE-1")
    assert out == {"call_sid": "c5797dcb", "to": "+919325642310"}
    assert saved == [("CASE-1", "call.started", {"to": "+919325642310", "call_sid": "c5797dcb"})]


def test_api_needs_login_and_vendor_crud(monkeypatch):
    assert client.post("/calls", json={"to": "+919325642310"}).status_code == 401
    assert client.get("/calls/status").status_code == 401
    monkeypatch.setattr(access, "get_user_state", lambda uid: access.UserState(uid, "v@x.co", "viewer", True))
    monkeypatch.setattr(access, "permissions_for_role", lambda role: frozenset({"vendors:read"}))
    token, _ = security.create_access_token("u1", "v@x.co", "viewer")
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/calls/status", headers=h).status_code == 200
    assert client.post("/calls", json={"to": "+919325642310"}, headers=h).status_code == 403


def test_the_old_public_webhooks_are_gone():
    for path in ("/voice/answer", "/voice/respond", "/voice/status"):
        assert client.post(path, data={"CallSid": "x"}).status_code == 404


# ---------------- Twilio ----------------

from app.clients import twilio_client  # noqa: E402


@pytest.fixture
def twilio(monkeypatch):
    monkeypatch.setattr(settings, "CALL_PROVIDER", "twilio")
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15005550006")
    monkeypatch.setattr(settings, "TWILIO_ANSWER_MESSAGE", "")
    monkeypatch.setattr(settings, "TWILIO_ANSWER_URL", "")  # paid-account behaviour unless a test says otherwise
    monkeypatch.setattr(settings, "CALL_ALLOWED_NUMBERS", [])


def capture_twilio(monkeypatch, body='{"sid": "CA123"}'):
    seen = {}

    def fake(request, timeout=0):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["params"] = dict(urllib.parse.parse_qsl(request.data.decode()))
        return FakeResponse(body.encode())

    monkeypatch.setattr(twilio_client.urllib.request, "urlopen", fake)
    return seen


def test_twilio_needs_a_from_number_to_be_ready(twilio, monkeypatch):
    assert twilio_client.is_configured()
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "")
    assert not twilio_client.is_configured()
    with pytest.raises(InvalidInput, match="isn't set up"):
        calling_agent.start_call("+919325642310", None)


def test_twilio_call_hangs_up_as_soon_as_they_answer(twilio, monkeypatch):
    seen = capture_twilio(monkeypatch)
    assert calling_agent.start_call("+919325642310", None) == {"call_sid": "CA123", "to": "+919325642310"}
    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Calls.json"
    assert seen["auth"] == "Basic " + base64.b64encode(b"ACtest:secret").decode()
    assert seen["params"]["To"] == "+919325642310" and seen["params"]["From"] == "+15005550006"
    assert seen["params"]["Twiml"] == "<Response><Hangup/></Response>"  # inline: no public URL needed


def test_twilio_trial_sends_only_to_from_and_a_hosted_url(twilio, monkeypatch):
    """A free trial rejected anything else ("limited parameter access"), so this is exactly what the console's own page sends."""
    monkeypatch.setattr(settings, "TWILIO_ANSWER_URL", "https://webhooks.twilio.com/v1/Voice/Template/voice_auto_response")
    seen = capture_twilio(monkeypatch)
    twilio_client.place_call("+919325642310")
    assert seen["params"] == {
        "To": "+919325642310", "From": "+15005550006",
        "Url": "https://webhooks.twilio.com/v1/Voice/Template/voice_auto_response",
    }


def test_twilio_can_say_a_line_before_hanging_up(twilio, monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_ANSWER_MESSAGE", "Test <call> & done")
    seen = capture_twilio(monkeypatch)
    twilio_client.place_call("+919325642310")
    assert seen["params"]["Twiml"] == "<Response><Say>Test &lt;call&gt; &amp; done</Say><Hangup/></Response>"


def test_twilios_refusal_is_shown_in_plain_words(twilio, monkeypatch):
    def refuse(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(
            b'{"code": 21219, "message": "The number +919325642310 is unverified. Trial accounts may only make calls to verified numbers."}'))

    monkeypatch.setattr(twilio_client.urllib.request, "urlopen", refuse)
    with pytest.raises(InvalidInput, match="Twilio refused the call: The number .* is unverified"):
        calling_agent.start_call("+919325642310", None)


def test_the_provider_is_chosen_by_setting_then_by_what_is_set_up(twilio, monkeypatch):
    assert calling_agent.provider() is twilio_client
    monkeypatch.setattr(settings, "CALL_PROVIDER", "exotel")
    assert calling_agent.provider() is exotel_client
    monkeypatch.setattr(settings, "CALL_PROVIDER", "")
    assert calling_agent.provider() is twilio_client  # fully set up -> Twilio
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "")
    assert calling_agent.provider() is exotel_client  # not set up -> falls back to Exotel


def test_a_call_can_be_ended_by_setting_its_status_to_completed(twilio, monkeypatch):
    seen = capture_twilio(monkeypatch, body="{}")
    calling_agent.end_call("CA0123456789abcdef0123456789abcdef")
    assert seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Calls/CA0123456789abcdef0123456789abcdef.json"
    assert seen["params"] == {"Status": "completed"}


def test_ending_rejects_odd_ids_and_other_providers(twilio, monkeypatch):
    for bad in ("../x", "CA 1", "a/b", "short"):
        with pytest.raises(InvalidInput, match="valid call id"):
            calling_agent.end_call(bad)
    monkeypatch.setattr(settings, "CALL_PROVIDER", "exotel")
    with pytest.raises(InvalidInput, match="only available with Twilio"):
        calling_agent.end_call("CA0123456789abcdef0123456789abcdef")


@pytest.mark.parametrize("code,message", [
    (400, "Call is not in-progress. Cannot redirect."),
    (404, "The requested resource /2010-04-01/Accounts/AC1/Calls/CA1.json was not found"),
])
def test_ending_a_call_that_already_finished_is_not_an_error(twilio, monkeypatch, code, message):
    def refuse(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, code, "x", {}, io.BytesIO(('{"message": "%s"}' % message).encode()))

    monkeypatch.setattr(twilio_client.urllib.request, "urlopen", refuse)
    calling_agent.end_call("CA0123456789abcdef0123456789abcdef")  # no exception: it is already ended


def test_other_twilio_failures_when_ending_are_still_reported(twilio, monkeypatch):
    def refuse(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 401, "x", {}, io.BytesIO(b'{"message": "Authenticate"}'))

    monkeypatch.setattr(twilio_client.urllib.request, "urlopen", refuse)
    with pytest.raises(InvalidInput, match="Authenticate"):
        calling_agent.end_call("CA0123456789abcdef0123456789abcdef")


def test_end_call_endpoint_needs_vendor_crud(monkeypatch):
    assert client.post("/calls/CA0123456789abcdef0123456789abcdef/end").status_code == 401
    monkeypatch.setattr(access, "get_user_state", lambda uid: access.UserState(uid, "v@x.co", "viewer", True))
    monkeypatch.setattr(access, "permissions_for_role", lambda role: frozenset({"vendors:read"}))
    token, _ = security.create_access_token("u1", "v@x.co", "viewer")
    assert client.post("/calls/CA0123456789abcdef0123456789abcdef/end", headers={"Authorization": f"Bearer {token}"}).status_code == 403
