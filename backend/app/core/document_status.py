"""Where a supplier's document is right now, worked out from the case's events: received -> reading -> read (matched / needs a person).
Pure function over the event list (oldest first, as the timeline returns it). The case page shows it live; the same rule is in the front end
(features/cases/documentStatus.ts), because the page only has the events."""

RECEIVED, READING, READ = "document.received", "document.reading", "document.read"
STUCK_AFTER_SECONDS = 180            # "reading" for longer than this means the read died without saying so: shown as needing a person


def current(events: list[dict], now=None) -> dict | None:
    """{"state": reading | matched | needs_person | other, "files": [...]} for the latest document, or None when no document has arrived.
    'reading' that has lasted longer than STUCK_AFTER_SECONDS is reported as needs_person: it must never sit on 'reading' for ever."""
    last = None
    for e in events:
        if e["event_type"] in (RECEIVED, READING, READ):
            last = e
    if last is None:
        return None
    payload = last.get("payload") or {}
    files = payload.get("files") or []
    if last["event_type"] == READ:
        outcome = payload.get("outcome")
        state = outcome if outcome in ("matched", "needs_person", "other") else "needs_person"
        return {"state": state, "files": files, "reason": payload.get("reason")}
    if now is not None and last.get("created_at") is not None and (now - last["created_at"]).total_seconds() > STUCK_AFTER_SECONDS:
        return {"state": "needs_person", "files": files, "reason": "Reading took too long."}
    return {"state": "reading", "files": files, "reason": None}
