"""Two people ask for the same item: offer to put them in one order (one request to suppliers, a better price, one delivery).

The system only SUGGESTS. A person decides, because combining changes what two requesters get. Only requests that are still
collecting or choosing between quotes (no order has gone out) can be combined; the older request carries on, the newer one
is folded into it.

Pure functions: no database or clock.
"""

import re
from datetime import datetime, timedelta

MERGEABLE_STAGES = frozenset({"sourcing_needed", "awaiting_quotes", "sourcing_stalled", "vendor_selected", "awaiting_approval"})
THRESHOLD = 0.6                     # how alike two item descriptions must be (1.0 = the same words)

SUGGESTED = "combine.suggested"
DISMISSED = "combine.dismissed"
MERGED_INTO = "case.merged_into"

_FILLER = frozenset({"a", "an", "the", "of", "for", "and", "with", "new", "pcs", "pc", "units", "unit", "nos", "no"})


def tokens(description: str) -> frozenset[str]:
    return frozenset(t for t in re.findall(r"[a-z0-9]+", str(description).lower()) if t not in _FILLER)


def similarity(a: str, b: str) -> float:
    """0 to 1: the share of words two descriptions have in common ("Steel rack" and "Steel storage rack" are alike; "Jetson
    16GB" and "Jetson 32GB" are not, because the size is part of what is wanted)."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def pair_items(primary: list[dict], secondary: list[dict]) -> list[tuple[dict, dict | None, float]]:
    """For each item of `secondary`, the most alike item of `primary` (each used once) or None. [(secondary_item, primary_item, score)]"""
    used: set[int] = set()
    out = []
    for s in secondary:
        best, best_i = 0.0, None
        for i, p in enumerate(primary):
            if i in used:
                continue
            score = similarity(s["description"], p["description"])
            if score > best:
                best, best_i = score, i
        if best_i is not None and best >= THRESHOLD:
            used.add(best_i)
            out.append((s, primary[best_i], best))
        else:
            out.append((s, None, best))
    return out


def overlap(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """The items the two requests share: [{"item", "primary_qty", "secondary_qty"}]. Empty when they have nothing in common."""
    return [{"item": p["description"], "primary_qty": p["quantity"], "secondary_qty": s["quantity"]}
            for s, p, _ in pair_items(primary, secondary) if p is not None]


def merged_items(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """The one order: shared items add up (under the primary's wording), anything only the secondary wanted is added as it is."""
    result = [dict(p) for p in primary]
    index = {p["description"]: i for i, p in enumerate(result)}
    for s, p, _ in pair_items(primary, secondary):
        if p is not None:
            result[index[p["description"]]]["quantity"] += s["quantity"]
        else:
            result.append({"description": s["description"], "quantity": s["quantity"]})
    return result


def candidates(case: dict, others: list[dict], window_hours: float, now: datetime) -> list[dict]:
    """Other requests this one could be combined with: open, no order yet, started recently, a different request.
    `case`/`others` need case_id, status, stage, created_at."""
    cutoff = now - timedelta(hours=window_hours)
    return [o for o in others
            if o["case_id"].lower() != case["case_id"].lower() and o["status"] == "open" and o["stage"] in MERGEABLE_STAGES and o["created_at"] >= cutoff]


def primary_of(a: dict, b: dict) -> tuple[dict, dict]:
    """(the request that carries on, the one folded into it): the older one carries on."""
    return (a, b) if a["created_at"] <= b["created_at"] else (b, a)


def open_suggestions(events: list[dict], cases_by_id: dict[str, dict]) -> list[dict]:
    """The suggestions still waiting for a person. `events` (oldest first) are combine/merge events across cases, each with the
    case it was recorded on (the NEWER request, which is the one that would be folded in). A suggestion ends when it is
    dismissed or merged, or when either request is no longer open and mergeable."""
    state: dict[tuple[str, str], dict | None] = {}
    for e in events:
        payload = e.get("payload") or {}
        newer = e["case_id"].lower()
        older = str(payload.get("primary_case_id") or "").lower()
        if not older:
            continue
        if e["event_type"] == SUGGESTED:
            state[(newer, older)] = {"newer": newer, "older": older, "matches": payload.get("matches", []), "since": e["created_at"]}
        elif e["event_type"] in (DISMISSED, MERGED_INTO):
            state[(newer, older)] = None
    out = []
    for suggestion in (s for s in state.values() if s):
        a, b = cases_by_id.get(suggestion["newer"]), cases_by_id.get(suggestion["older"])
        if a and b and all(c["status"] == "open" and c["stage"] in MERGEABLE_STAGES for c in (a, b)):
            out.append(suggestion)
    return sorted(out, key=lambda s: s["since"])
