"""The requester's own confirmation that the goods reached them. A second check next to Receiving's.

Receiving marking the goods received is still what moves the case on. After that the person who asked is
asked "did you get it?". A "no" alerts Receiving (it appears in their My work as urgent) until Receiving
records that they followed up. Nothing here blocks the case: a requester who never answers costs nothing.

Pure functions over case events; no database.
"""

CONFIRMED = "delivery.requester_confirmed"
DISPUTED = "delivery.requester_disputed"
HANDLED = "delivery.dispute_handled"
RECEIPT_EVENTS = (CONFIRMED, DISPUTED, HANDLED)

NOTE_MAX = 500


def _latest(events: list[dict]) -> dict | None:
    """The newest of the three receipt events, from events in any order."""
    mine = [e for e in events if e["event_type"] in RECEIPT_EVENTS]
    return max(mine, key=lambda e: e["created_at"]) if mine else None


def receipt_state(delivered: bool, events: list[dict]) -> dict:
    """What the requester should see: not_delivered | ask | confirmed | disputed | followed_up.
    `followed_up` means they said no and Receiving has since looked into it, so they are asked again."""
    if not delivered:
        return {"state": "not_delivered", "note": None, "at": None}
    last = _latest(events)
    if last is None:
        return {"state": "ask", "note": None, "at": None}
    state = {CONFIRMED: "confirmed", DISPUTED: "disputed", HANDLED: "followed_up"}[last["event_type"]]
    return {"state": state, "note": (last.get("payload") or {}).get("note"), "at": last["created_at"]}


def open_disputes(rows: list[dict]) -> dict[str, dict]:
    """From receipt events across all cases ({case_id, event_type, payload, created_at}): the cases where the
    requester's latest word is still "not received", as {case_id: {"note", "since", "by"}}."""
    latest: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: r["created_at"]):
        latest[row["case_id"].lower()] = row
    return {
        case_id: {"note": (r.get("payload") or {}).get("note"), "since": r["created_at"], "by": (r.get("payload") or {}).get("by")}
        for case_id, r in latest.items() if r["event_type"] == DISPUTED
    }


def clean_note(note: str | None) -> str | None:
    note = (note or "").strip()
    return note[:NOTE_MAX] or None
