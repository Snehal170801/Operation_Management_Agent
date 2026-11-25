"""A supplier changes the price after quoting ("steel went up, it is now Rs 30,000").

Money is never accepted silently: a higher price goes to a person. A lower price is simply taken. A price that is the same
(within a small tolerance) is just a confirmation. A number that makes no sense is treated as a problem to read, not as a price.

Pure functions: no database or clock.
"""

LATEST_QUOTE_NOTE = "Where a supplier has quoted more than once, the latest price counts."


def clean_price(value) -> float | None:
    """The price a supplier stated, as a number, or None if it is missing or not a usable amount."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(",", "").replace("₹", "").replace("Rs", "").strip())
    except ValueError:
        return None
    return round(number, 2) if number > 0 and number == number and number != float("inf") else None


def assess(agreed_total: float | None, new_total, tolerance_pct: float, absurd_factor: float = 10.0) -> dict:
    """What to do with a price a supplier has just stated for an order agreed at `agreed_total`:
      confirm   same price (within the tolerance): nothing to decide
      lower     cheaper: take it
      higher    dearer: a person must decide (`pct` says by how much)
      unclear   cannot be compared (no agreed price, unreadable, or wildly different): a person reads the reply
    """
    new = clean_price(new_total)
    if new is None or not agreed_total or agreed_total <= 0:
        return {"action": "unclear", "pct": None, "new_total": new}
    if new > agreed_total * absurd_factor or new < agreed_total / absurd_factor:
        return {"action": "unclear", "pct": None, "new_total": new}
    pct = round((new - agreed_total) / agreed_total * 100, 1)
    if abs(new - agreed_total) <= agreed_total * tolerance_pct / 100:
        return {"action": "confirm", "pct": pct, "new_total": new}
    return {"action": "higher" if new > agreed_total else "lower", "pct": pct, "new_total": new}


def reason(vendor: str, po_number: str, agreed_total: float, new_total: float, pct: float) -> str:
    return f"{vendor} now asks ₹{new_total:,.0f} for {po_number}, up {pct:g}% from the agreed ₹{agreed_total:,.0f}."
