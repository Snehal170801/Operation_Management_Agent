"""A supplier may quote more than once (a revised price). The latest one is the one that counts.

Pure functions over quote dicts (vendor_id, price, created_at). Rows are expected oldest first, as the repository returns them,
which also breaks a tie in time.
"""

from datetime import datetime


def latest_per_vendor(quotes: list[dict]) -> list[dict]:
    """One quote per supplier: their most recent priced quote (or, if none has a readable price, their most recent).
    Order of first appearance is kept."""
    best: dict[str, tuple] = {}
    order: list[str] = []
    for i, q in enumerate(quotes):
        key = q["vendor_id"].lower()
        if key not in best:
            order.append(key)
        rank = (q.get("price") is not None, q.get("created_at") or datetime.min, i)          # priced beats unpriced, then newest
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, q)
    return [best[k][1] for k in order]


def vendor_count(quotes: list[dict]) -> int:
    """How many different suppliers have quoted (three quotes from one supplier is still one quote to compare)."""
    return len({q["vendor_id"].lower() for q in quotes})
