"""Minimal Exotel voice client (no SDK): ring a phone and connect it to a call flow (app) or to a second number."""

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from app.core.config import settings


def is_configured() -> bool:
    has_target = bool(settings.EXOTEL_APP_ID or settings.EXOTEL_CONNECT_TO)
    return all([settings.EXOTEL_ACCOUNT_SID, settings.EXOTEL_API_KEY, settings.EXOTEL_API_TOKEN, settings.EXOTEL_FROM_NUMBER]) and has_target


def _call_sid(body: str) -> str:
    """Exotel answers in JSON ({"Call": {"Sid": ...}}) or XML (<Sid>...</Sid>) depending on the account; accept both."""
    try:
        return str(json.loads(body)["Call"]["Sid"])
    except (ValueError, KeyError, TypeError):
        match = re.search(r"<Sid>([^<]+)</Sid>", body)
        if match:
            return match.group(1)
    raise RuntimeError("Exotel accepted the request but returned no call id.")


def _error_text(body: str) -> str:
    match = re.search(r"<Message>([^<]+)</Message>", body) or re.search(r'"Message"\s*:\s*"([^"]+)"', body)
    return match.group(1) if match else ""


def place_call(to: str) -> str:
    """Rings `to` first. When they pick up, Exotel runs the configured flow (or dials the connect-to number).

    Returns Exotel's call id. Raises RuntimeError carrying Exotel's own reason if it refuses.
    """
    params = {"From": to, "CallerId": settings.EXOTEL_FROM_NUMBER, "CallType": "trans", "TimeOut": "30"}
    if settings.EXOTEL_TIME_LIMIT > 0:
        params["TimeLimit"] = str(settings.EXOTEL_TIME_LIMIT)
    if settings.EXOTEL_APP_ID:
        # Run the call flow you built in the Exotel dashboard once the person answers.
        params["Url"] = f"http://my.exotel.in/exoml/start/{settings.EXOTEL_APP_ID}"
    else:
        params["To"] = settings.EXOTEL_CONNECT_TO

    url = f"https://{settings.EXOTEL_HOST}/v1/Accounts/{settings.EXOTEL_ACCOUNT_SID}/Calls/connect"
    request = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), method="POST")
    token = base64.b64encode(f"{settings.EXOTEL_API_KEY}:{settings.EXOTEL_API_TOKEN}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return _call_sid(response.read().decode())
    except urllib.error.HTTPError as exc:
        reason = _error_text(exc.read().decode(errors="replace"))
        raise RuntimeError(reason or f"Exotel refused the call (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Exotel ({exc.reason}).") from exc
