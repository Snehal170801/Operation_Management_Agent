"""Calling Agent (demo): rings a phone through Exotel and connects it to a call flow.

The spoken content comes from the call flow you build in the Exotel dashboard (e.g. "daccess4 Landing Flow"),
so this version places real calls but does not hold an AI conversation. Each call is noted on the case timeline.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from app.agents import operations_agent
from app.clients import exotel_client, twilio_client
from app.core.config import settings
from app.core import automation
from app.core.exceptions import InvalidInput
from app.repositories import vendor_repository

logger = logging.getLogger(__name__)

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def provider():
    """The calling service in use: CALL_PROVIDER if set, else Twilio when fully set up, else Exotel."""
    if settings.CALL_PROVIDER == "twilio":
        return twilio_client
    if settings.CALL_PROVIDER == "exotel":
        return exotel_client
    return twilio_client if twilio_client.is_configured() else exotel_client


def is_configured() -> bool:
    return provider().is_configured()


def start_call(to: str, case_id: str | None) -> dict:
    service = provider()
    if not service.is_configured():
        raise InvalidInput(
            "Calling isn't set up yet: add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER "
            "(or the EXOTEL_* settings) to the backend .env."
        )
    if not _E164.match(to):
        raise InvalidInput("Enter the number with country code, like +919876543210.")
    if settings.CALL_ALLOWED_NUMBERS and to not in settings.CALL_ALLOWED_NUMBERS:
        raise InvalidInput("That number isn't on the allowed list for demo calls (CALL_ALLOWED_NUMBERS).")

    try:
        sid = service.place_call(to)
    except RuntimeError as exc:
        # The provider's own reason, e.g. an unverified account or number.
        name = "Twilio" if service is twilio_client else "Exotel"
        raise InvalidInput(f"{name} refused the call: {exc}") from exc

    if case_id:
        try:
            operations_agent.publish_event(case_id, "call.started", agent_name="Calling Agent", payload={"to": to, "call_sid": sid})
        except Exception:
            logger.exception("could not note the call on case %s", case_id)
    return {"call_sid": sid, "to": to}


_CALL_SID = re.compile(r"^[A-Za-z0-9]{10,64}$")


def end_call(call_sid: str) -> None:
    """Hang up a call this app started."""
    if not _CALL_SID.match(call_sid):
        raise InvalidInput("That isn't a valid call id.")
    service = provider()
    if service is not twilio_client:
        raise InvalidInput("Ending a call from here is only available with Twilio. Hang up on the phone instead.")
    try:
        twilio_client.end_call(call_sid)
    except RuntimeError as exc:
        # A call that has already finished (the usual case: a short call ends by itself before anyone presses End)
        # can't be changed, and Twilio then says "not found" / "not in-progress". The goal is met, so that is fine.
        if re.search(r"not found|not in-progress|already|completed|cannot redirect", str(exc), re.IGNORECASE):
            return
        raise InvalidInput(f"Twilio could not end the call: {exc}") from exc


# ---------------------------------------------------------------------------------------------
# "Please check your email" call, made after the system emails a vendor.

_IST = timezone(timedelta(hours=5, minutes=30))
_LANGUAGE_CODES = {"hi": "hi-IN", "mr": "mr-IN", "en": "en-IN"}

# What is said (twice, so a quick listener catches it). Have a native speaker review the wording before real use.
_MESSAGES = {
    "hi": {
        "rfq": "नमस्कार, मैं {company} की ओर से एक स्वचालित सहायक बोल रहा हूँ। कृपया अपना ईमेल देखिए। मैंने आपको कुछ जानकारी भेजी है। धन्यवाद।",
        "po": "नमस्कार, मैं {company} की ओर से एक स्वचालित सहायक बोल रहा हूँ। कृपया अपना ईमेल देखिए। मैंने आपको खरीद आदेश भेजा है। धन्यवाद।",
    },
    "mr": {
        "rfq": "नमस्कार, मी {company} कडून एक स्वयंचलित सहाय्यक बोलत आहे. कृपया तुमचा ईमेल तपासा. मी तुम्हाला काही माहिती पाठवली आहे. धन्यवाद.",
        "po": "नमस्कार, मी {company} कडून एक स्वयंचलित सहाय्यक बोलत आहे. कृपया तुमचा ईमेल तपासा. मी तुम्हाला खरेदी आदेश पाठवला आहे. धन्यवाद.",
    },
    "en": {
        "rfq": "Hello, this is an automated assistant calling on behalf of {company}. Please check your email. I have sent you some details. Thank you.",
        "po": "Hello, this is an automated assistant calling on behalf of {company}. Please check your email. I have sent you a purchase order. Thank you.",
    },
}


def message_for(language: str, kind: str) -> str:
    texts = _MESSAGES.get(language) or _MESSAGES["hi"]
    return (texts.get(kind) or texts["rfq"]).format(company=settings.CALL_COMPANY_NAME)


def _voice_for(language: str) -> str:
    return {"hi": settings.CALL_VOICE_HI, "mr": settings.CALL_VOICE_MR}.get(language, settings.CALL_VOICE_EN)


def _within_calling_hours(now: datetime | None = None) -> bool:
    hour = (now or datetime.now(_IST)).astimezone(_IST).hour
    return settings.CALL_HOURS_START <= hour < settings.CALL_HOURS_END


def _already_called(case_id: str, vendor_id: str, kind: str) -> bool:
    for event in operations_agent.get_case_events(case_id):
        payload = event.get("payload") or {}
        if event["event_type"] == "call.notified" and payload.get("vendor_id") == vendor_id and payload.get("kind") == kind:
            return True
    return False


def notify_email_sent(case_id: str, vendor_names: list[str], kind: str) -> list[str]:
    """After vendors were emailed, ring each one who has a phone number and say, in their language, to check
    their email. Never raises: a failed call must not break the case. Returns the names that were called."""
    if not settings.CALL_AFTER_EMAIL or not vendor_names:
        return []
    try:
        return _notify(case_id, set(n.lower() for n in vendor_names), kind)
    except Exception:
        logger.exception("check-your-email calls failed for case %s", case_id)
        return []


def _notify(case_id: str, names: set[str], kind: str) -> list[str]:
    def skip(reason: str, vendor: str | None = None) -> list[str]:
        operations_agent.publish_event(case_id, "call.skipped", agent_name="Calling Agent",
                                       payload={"reason": reason, "vendor": vendor, "kind": kind})
        return []

    if automation.is_paused():
        return skip("automation is paused")
    if provider() is not twilio_client or not twilio_client.can_speak_custom_message():
        return skip("calling in Hindi/Marathi needs a paid Twilio account (TWILIO_ANSWER_URL must be empty)")
    if not _within_calling_hours():
        return skip(f"outside calling hours ({settings.CALL_HOURS_START}:00-{settings.CALL_HOURS_END}:00 India time)")

    called = []
    for row in vendor_repository.find_all_vendors():
        if row.name.lower() not in names:
            continue
        vendor_id = str(row.vendor_id)
        if not row.phone:
            continue  # no phone on file: the email is all they get
        if settings.CALL_ALLOWED_NUMBERS and row.phone not in settings.CALL_ALLOWED_NUMBERS:
            skip("number is not on the allowed list", row.name)
            continue
        if _already_called(case_id, vendor_id, kind):
            continue
        language = row.call_language if row.call_language in _LANGUAGE_CODES else "hi"
        try:
            sid = twilio_client.place_message_call(
                row.phone, message_for(language, kind), _LANGUAGE_CODES[language], _voice_for(language)
            )
        except RuntimeError as exc:
            skip(f"Twilio refused the call: {exc}", row.name)
            continue
        operations_agent.publish_event(
            case_id, "call.notified", agent_name="Calling Agent",
            payload={"vendor": row.name, "vendor_id": vendor_id, "kind": kind, "language": language, "call_sid": sid},
        )
        called.append(row.name)
    return called
