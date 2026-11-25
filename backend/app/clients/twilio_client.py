"""Minimal Twilio voice client (no SDK). Places a call whose instructions are sent inline, so no public URL is needed."""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from app.core.config import settings


def is_configured() -> bool:
    return all([settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_FROM_NUMBER])


def _twiml() -> str:
    """What to do when the person answers: say a short line (optional), then hang up."""
    message = settings.TWILIO_ANSWER_MESSAGE.strip()
    if message:
        safe = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<Response><Say>{safe}</Say><Hangup/></Response>"
    return "<Response><Hangup/></Response>"


def place_call(to: str) -> str:
    """Rings `to`. Returns Twilio's call SID. Raises RuntimeError carrying Twilio's own reason if it refuses."""
    params = {"To": to, "From": settings.TWILIO_FROM_NUMBER}
    if settings.TWILIO_ANSWER_URL:
        # Trial accounts may only send To, From and a Twilio-hosted Url ("limited parameter access").
        params["Url"] = settings.TWILIO_ANSWER_URL
    else:
        params["Twiml"] = _twiml()  # paid accounts: instructions inline, so no public URL is needed
        params["Timeout"] = "30"
    form = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Calls.json", data=form, method="POST"
    )
    token = base64.b64encode(f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return str(json.loads(response.read())["sid"])
    except urllib.error.HTTPError as exc:
        # Twilio explains the problem in JSON (e.g. "unverified number" on a trial account).
        try:
            message = json.loads(exc.read()).get("message", "")
        except Exception:
            message = ""
        raise RuntimeError(message or f"Twilio refused the call (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Twilio ({exc.reason}).") from exc
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Twilio accepted the request but returned no call id.") from exc


def end_call(call_sid: str) -> None:
    """Hangs up a call that is ringing or in progress. Raises RuntimeError with Twilio's own reason if it can't."""
    form = urllib.parse.urlencode({"Status": "completed"}).encode()
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Calls/{call_sid}.json", data=form, method="POST"
    )
    token = base64.b64encode(f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=20):
            return
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read()).get("message", "")
        except Exception:
            message = ""
        raise RuntimeError(message or f"Twilio could not end the call (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Twilio ({exc.reason}).") from exc


def can_speak_custom_message() -> bool:
    """Custom spoken text needs inline instructions, which a free trial blocks (see TWILIO_ANSWER_URL)."""
    return is_configured() and not settings.TWILIO_ANSWER_URL


def place_message_call(to: str, text: str, language: str, voice: str) -> str:
    """Rings `to`, speaks `text` in `language` with `voice`, then hangs up. Returns the call SID."""
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    twiml = f'<Response><Pause length="1"/><Say language="{language}" voice="{voice}">{safe}</Say><Pause length="1"/><Hangup/></Response>'
    form = urllib.parse.urlencode({"To": to, "From": settings.TWILIO_FROM_NUMBER, "Twiml": twiml, "Timeout": "30"}).encode()
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Calls.json", data=form, method="POST"
    )
    token = base64.b64encode(f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return str(json.loads(response.read())["sid"])
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read()).get("message", "")
        except Exception:
            message = ""
        raise RuntimeError(message or f"Twilio refused the call (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Twilio ({exc.reason}).") from exc
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Twilio accepted the request but returned no call id.") from exc
