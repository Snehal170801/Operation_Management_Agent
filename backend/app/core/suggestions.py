"""One sentence that tells a person what the system makes of a decision, and what it would do, to save them reading
tables: "Matches the order", or "Doesn't match: the total is ₹25,000 (26%) higher than the order. Suggest: reject."

These are rules over the real numbers, not text written by an AI, so a sentence is never wrong about an amount.
Pure functions. A suggestion is advice: the person still decides.
"""

SMALL_GAP_PCT = 5  # a total off by no more than this much, with nothing else wrong, is "a small gap"


def rupees(value) -> str:
    if value is None:
        return "—"
    return f"₹{value:,.0f}" if float(value).is_integer() else f"₹{value:,.2f}"


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def invoice_suggestion(invoice: dict, po: dict | None, goods_received: bool, tolerance_pct: float) -> dict | None:
    """{"verdict": match | waiting | mismatch | check, "text": one sentence} for an invoice still waiting on a person
    (or cleared by the agent), or None once a person has already decided it."""
    status = invoice["status"]
    if status in ("approved", "rejected"):
        return None
    issues = invoice.get("issues") or []
    number, total = invoice.get("invoice_number"), invoice.get("total_amount")

    if status == "matched":
        return {"verdict": "match", "text": "Matches the order and the receipt. Nothing for you to do."}

    if any("duplicate" in i.lower() for i in issues):
        return {"verdict": "mismatch", "text": f"Looks like a duplicate: invoice {number or '(no number)'} was already sent by this supplier. Suggest: reject."}

    if total is None or not number:
        what = "total" if total is None else "invoice number"
        return {"verdict": "check", "text": f"Couldn't read the {what} from the supplier's email. Suggest: open the email and enter it by hand, or ask for a clearer copy."}

    agreed = (po or {}).get("total_amount")
    if agreed:
        diff = total - agreed
        if abs(diff) > abs(agreed) * tolerance_pct / 100:
            pct = abs(diff) / abs(agreed) * 100
            others = [i for i in issues if "differs from the purchase order total" not in i]
            core = (f"Doesn't match: the total is {rupees(abs(diff))} ({pct:.0f}%) {'higher' if diff > 0 else 'lower'} than the order "
                    f"({rupees(total)} against {rupees(agreed)}).")
            more = f" Also: {_sentence(others[0])}" if others else ""
            if diff < 0:
                tail = " Suggest: ask the supplier whether anything is missing, then reject or approve."
            elif pct <= SMALL_GAP_PCT and not others:
                tail = " A small gap: approve anyway only if the supplier explained it, otherwise reject."
            else:
                tail = " Suggest: reject and ask for a corrected invoice."
            return {"verdict": "mismatch", "text": core + more + tail}

    if status == "mismatch":
        reason = _sentence(issues[0]) if issues else "It could not be matched to the order."
        return {"verdict": "mismatch", "text": f"Doesn't match: {reason} Suggest: reject and ask for a corrected invoice."}

    # on hold: nothing is wrong, the goods are just not confirmed yet
    return {"verdict": "waiting", "text": f"Matches the order ({rupees(total)}). Waiting for Receiving to confirm the goods arrived; it clears by itself after that."}


def approval_suggestion(options: list[dict], ai_pick_id: str | None, needed_by=None) -> str | None:
    """What to do about an order that needs a person's decision, naming the pick and what the other suppliers offer."""
    if not options:
        return "No supplier has replied yet. Wait for quotes before deciding."
    pick = next((o for o in options if o["vendor_id"] == ai_pick_id), options[0])
    if pick["price"] is None:
        return f"{pick['vendor_name']} gave no readable price. Suggest: open their reply and check it before approving."
    late = [o for o in options if "Too late" in o.get("tags", [])]
    if needed_by and len(late) == len(options):
        return (f"None of the suppliers can deliver by {needed_by:%d %b}. Suggest: ask for a faster delivery, or approve {pick['vendor_name']} "
                f"({rupees(pick['price'])}, {pick['lead_time_days']} days) knowing it will arrive late.")
    on_time = [o for o in options if "Arrives in time" in o.get("tags", [])]
    if needed_by and "Too late" in pick.get("tags", []) and on_time:
        pick = min(on_time, key=lambda o: o["price"] if o["price"] is not None else float("inf"))      # the pick cannot make the date, one of the others can
    detail = ", ".join(x for x in (rupees(pick["price"]),
                                   f"{pick['lead_time_days']} days" if pick["lead_time_days"] is not None else None, pick["terms"]) if x)
    if len(options) == 1:
        return f"Only {pick['vendor_name']} has replied ({detail}). Suggest: approve if that price is acceptable, or wait for more quotes."

    text = f"Suggest: approve {pick['vendor_name']} ({detail})."
    priced = [o for o in options if o["price"] is not None]
    timed = [o for o in options if o["lead_time_days"] is not None]
    cheapest = min(priced, key=lambda o: o["price"], default=None)
    fastest = min(timed, key=lambda o: o["lead_time_days"], default=None)
    if cheapest and cheapest["vendor_id"] != pick["vendor_id"]:
        slower = (cheapest["lead_time_days"] or 0) - (pick["lead_time_days"] or 0)
        text += f" {cheapest['vendor_name']} is {rupees(pick['price'] - cheapest['price'])} cheaper" + (f" but {slower} days slower." if slower > 0 else ".")
    if fastest and fastest["vendor_id"] not in (pick["vendor_id"], (cheapest or {}).get("vendor_id")):
        dearer = (fastest["price"] or 0) - pick["price"]
        faster = (pick["lead_time_days"] or 0) - fastest["lead_time_days"]
        text += f" {fastest['vendor_name']} is {faster} days faster" + (f" but {rupees(dearer)} dearer." if dearer > 0 else ".")
    return text
