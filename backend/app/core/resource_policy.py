"""Sending a request back out for new quotes ("re-sourcing") after an approver rejects the offers.

A rejection can either end the request or ask the suppliers again. To stop a request going round forever, asking
again is allowed only a limited number of times. Pure functions over the case's events; no database.
"""

REJECTED = "approval.rejected"


def rounds_used(events: list[dict]) -> int:
    """How many times this case has already been sent back out for new quotes."""
    return sum(1 for e in events if e["event_type"] == REJECTED and (e.get("payload") or {}).get("re_sourcing"))


def can_resource(events: list[dict], max_rounds: int) -> bool:
    return rounds_used(events) < max_rounds


def round_number(events: list[dict]) -> int:
    """1 for the first set of quotes, 2 after one re-ask, and so on."""
    return rounds_used(events) + 1
