"""Negotiation: after the best quote is chosen, the supplier is asked ONCE for a better price. A lower reply is taken; anything else keeps the
original quote. The approval rules still decide (a negotiated price goes through the same policy as any quote). Off unless switched on.

Pure functions over events, prices and a clock: no database, e-mail or AI.
"""

from datetime import datetime, timedelta

STAGE = "negotiating"
ASKED = "negotiation.asked"
RESTART_EVENTS = ("sourcing.restarted",)
SUSPICIOUS_BELOW = 0.2         # a "better" price under a fifth of the original is almost surely a misreading (a unit price, say): a person checks it


def asked_this_round(events: list[dict]) -> dict | None:
    """The negotiation already started for the current round of quotes (a round begins at the case start or when suppliers were asked again),
    as its payload {vendor_id, vendor, original_price}; None if none. This is what keeps it to ONE ask per round."""
    last = None
    for e in events:
        if e["event_type"] in RESTART_EVENTS:
            last = None
        elif e["event_type"] == ASKED:
            last = {**(e.get("payload") or {}), "at": e.get("created_at")}
    return last


OUTCOMES = {"negotiation.improved": "improved", "negotiation.no_improvement": "kept", "negotiation.no_reply": "no_reply", "negotiation.skipped": "skipped"}


def note(events: list[dict]) -> dict | None:
    """What an approver should know about the negotiation of this round, or None when the supplier was never asked.
    {vendor, outcome: waiting | improved | kept | no_reply, original_price, new_price, saving, text}. The same facts as the case timeline, in one sentence."""
    asked_at = None
    for i, e in enumerate(events):
        if e["event_type"] in RESTART_EVENTS:
            asked_at = None
        elif e["event_type"] == ASKED:
            asked_at = i
    if asked_at is None:
        return None
    asked = events[asked_at].get("payload") or {}
    vendor, original = asked.get("vendor") or "The supplier", asked.get("original_price")
    outcome, new, why = "waiting", None, None
    for e in events[asked_at + 1:]:
        kind = OUTCOMES.get(e["event_type"])
        if kind and kind != "skipped":
            payload = e.get("payload") or {}
            outcome, new, why = kind, payload.get("new_price"), payload.get("why")
    price = f"{original:,.2f}" if original is not None else "their quote"
    if outcome == "improved" and new is not None and original:
        text = f"{vendor} was asked for a better price and lowered it from {price} to {new:,.2f} (saves {original - new:,.2f}, {100 * (original - new) / original:.1f}%)."
    elif outcome == "kept":
        text = f"{vendor} was asked for a better price and did not lower it: the original quote of {price} stands."
    elif outcome == "no_reply":
        text = f"{vendor} was asked for a better price and did not answer in time: the original quote of {price} stands."
    else:
        text = f"{vendor} was asked for a better price; still waiting for the answer."
    return {"vendor": vendor, "outcome": outcome, "original_price": original, "new_price": new if outcome == "improved" else None,
            "saving": round(original - new, 2) if outcome == "improved" and new is not None and original else None, "text": text, "why": why}


def should_ask(enabled: bool, events: list[dict], price: float | None, vendor_email: str | None) -> str | None:
    """None when the supplier should be asked now, otherwise the plain reason it is not (for the case timeline when it matters)."""
    if not enabled:
        return "off"
    if price is None or price <= 0:
        return "no price"
    if not (vendor_email or "").strip():
        return "no e-mail address"
    if asked_this_round(events) is not None:
        return "already asked"
    return None


def verdict(original: float | None, reply: float | None) -> str:
    """What a supplier's answer is worth: improved | same_or_higher | unreadable | suspicious. Only 'improved' changes the price."""
    if original is None or reply is None or reply <= 0:
        return "unreadable"
    if reply >= original:
        return "same_or_higher"
    if reply < original * SUSPICIOUS_BELOW:
        return "suspicious"
    return "improved"


def is_due(asked_at: datetime | None, now: datetime, wait_hours: float) -> bool:
    """The supplier has had long enough to answer, so the original quote stands."""
    return asked_at is not None and now - asked_at >= timedelta(hours=wait_hours)


def message(vendor: str, items: list[dict], price: float, wait_hours: float) -> str:
    lines = "\n".join(f"  - {i['description']} x {i['quantity']}" for i in items)
    return (f"Dear {vendor},\n\nThank you for your quotation of {price:,.2f} for:\n\n{lines}\n\n"
            f"It is among the best we have received. Before we decide, can you offer a better total price? If you can, please reply with your new "
            f"total price and delivery time. If your quotation already is your best, you do not need to reply: it stands as it is.\n\n"
            f"We will decide within about {wait_hours:g} hours.\n\nThank you.")


def summary(original: float, new: float) -> str:
    return f"{original:,.2f} -> {new:,.2f} (saves {original - new:,.2f}, {100 * (original - new) / original:.1f}%)"
