"""Everything a person needs to decide an order: what was asked, every supplier's reply in their own words, the AI's
ranking with its reasons, and who is currently chosen. Pure function: the controller gathers the facts.
"""

from datetime import date, datetime, timezone

from app.core import negotiation, quote_expiry
from app.core import quotes as quote_rules
from app.core import resource_policy, urgency
from app.core.suggestions import approval_suggestion


def _latest_ranking(events: list[dict]) -> list[dict]:
    for e in reversed(events):
        ranking = (e.get("payload") or {}).get("ranking") if e["event_type"] == "vendor.selected" else None
        if ranking:
            return ranking
    return []


def build_review(approval: dict, case: dict, request: dict | None, quotes: list[dict], vendors: dict, selection: dict | None,
                 events: list[dict], max_rounds: int = 0, today: date | None = None, now=None, preferred_vendor_ids=()) -> dict:
    ranking = {r["vendor_id"]: r for r in _latest_ranking(events)}

    # one row per supplier: their latest priced quote (a revised price replaces the earlier one)
    best = {q["vendor_id"]: q for q in quote_rules.latest_per_vendor(quotes)}

    priced = [q for q in best.values() if q["price"] is not None]
    timed = [q for q in best.values() if q["lead_time_days"] is not None]
    cheapest = min((q["price"] for q in priced), default=None)
    fastest = min((q["lead_time_days"] for q in timed), default=None)
    ai_pick = next((v for v, r in ranking.items() if r["rank"] == 1), selection["vendor_id"] if selection else None)

    def order(q):
        r = ranking.get(q["vendor_id"])
        return (r["rank"] if r else 10_000, q["price"] if q["price"] is not None else float("inf"))

    needed_by = (request or {}).get("needed_by")
    today = today or date.today()
    options = []
    for q in sorted(best.values(), key=order):
        v = vendors.get(q["vendor_id"]) or {}
        r = ranking.get(q["vendor_id"])
        tags = []
        if q["vendor_id"] == ai_pick:
            tags.append("AI's pick")
        if str(q["vendor_id"]).lower() in {str(p).lower() for p in preferred_vendor_ids}:
            tags.append("Preferred supplier")
        if cheapest is not None and q["price"] == cheapest:
            tags.append("Cheapest")
        if fastest is not None and q["lead_time_days"] == fastest:
            tags.append("Fastest")
        validity = quote_expiry.tag(q, now or datetime.now(timezone.utc).replace(tzinfo=None))
        if validity:
            tags.append(validity)
        in_time = urgency.meets(q["lead_time_days"], needed_by, today)
        if in_time is True:
            tags.append("Arrives in time")
        elif in_time is False:
            tags.append("Too late")
        options.append({
            "rank": r["rank"] if r else None, "vendor_id": q["vendor_id"], "vendor_name": q["vendor_name"], "email": v.get("email"),
            "price": q["price"], "lead_time_days": q["lead_time_days"], "terms": q["terms"],
            "reliability": v.get("reliability_score"), "reply_text": (q.get("raw_quote_text") or "")[:600],
            "reason": (r or {}).get("reason") or None, "tags": tags,
        })

    return {
        "approval_id": approval["approval_id"], "case_id": approval["case_id"], "case_number": case.get("case_number"),
        "status": approval["status"], "reasons": approval["reasons"], "requested_by": case.get("requester_id"),
        "request_text": (request or {}).get("raw_request"), "items": (request or {}).get("items", []),
        "recommended_vendor_id": ai_pick, "selected_vendor_id": selection["vendor_id"] if selection else None,
        "rationale": selection["rationale"] if selection else None, "options": options,
        "suggestion": approval_suggestion(options, ai_pick, needed_by),
        "urgent": bool((request or {}).get("urgent")), "needed_by": needed_by,
        # Which round of quotes this is, why an earlier round was turned down, and whether asking again is still allowed.
        "negotiation": negotiation.note(events),
        "round": resource_policy.round_number(events),
        "earlier_note": next(((e.get("payload") or {}).get("note") for e in reversed(events)
                              if e["event_type"] == resource_policy.REJECTED and (e.get("payload") or {}).get("re_sourcing")), None),
        "can_ask_again": approval["status"] == "pending" and resource_policy.can_resource(events, max_rounds),
    }
