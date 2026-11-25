"""Turns the AI's answer about the quotes into a clean ranking: every supplier that quoted, best first, each with
a reason. The AI is not trusted to be tidy: unknown ids are dropped, repeats are ignored, anyone it forgot is
added at the end, and if it gave no ranking at all the old single pick still works. Pure function.
"""

MAX_REASON = 400


def _price_key(quote: dict) -> float:
    return quote["price"] if quote.get("price") is not None else float("inf")


def normalize_ranking(result: dict, quotes: list[dict]) -> tuple[list[dict], str]:
    """Returns (ranking, rationale). `ranking` is [{"vendor_id", "rank", "reason"}] best first and always lists every
    supplier in `quotes` exactly once; `rationale` is why the first one is best overall."""
    cheapest_first = sorted(quotes, key=_price_key)
    known: list[str] = []
    for q in cheapest_first:
        if q["vendor_id"] not in known:
            known.append(q["vendor_id"])

    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    raw = result.get("ranking")
    for entry in raw if isinstance(raw, list) else []:
        vendor_id = entry.get("vendor_id") if isinstance(entry, dict) else None
        if vendor_id in known and vendor_id not in seen:
            seen.add(vendor_id)
            ordered.append((vendor_id, str(entry.get("reason") or "").strip()[:MAX_REASON]))

    if not ordered:  # no usable ranking: the single pick (if it is a real supplier) goes first
        pick = result.get("recommended_vendor_id")
        if pick in known:
            seen.add(pick)
            ordered.append((pick, str(result.get("rationale") or "").strip()[:MAX_REASON]))

    for vendor_id in known:  # anyone the AI left out follows, cheapest first
        if vendor_id not in seen:
            ordered.append((vendor_id, "The AI did not rank this supplier."))

    ranking = [{"vendor_id": v, "rank": i + 1, "reason": reason} for i, (v, reason) in enumerate(ordered)]
    rationale = str(result.get("rationale") or "").strip() or (ranking[0]["reason"] if ranking else "")
    return ranking, rationale
