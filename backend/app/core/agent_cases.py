"""Rules for the cases around the other agents: who can really approve, goods that arrive wrongly, stock given back, a user who has left.

Pure functions over plain dicts: no database, clock or e-mail. The pipeline decides when to ask and what to tell people.
"""

from app.core.approver_leave import effective_approvers, on_leave

ADMIN_ROLE = "admin"


# ---- Approval: is there anyone who can actually decide this? ----------------------------------------------------------------------------------

def approver_cover(approvers: list[dict], requester: str | None, directory: dict | None = None, today=None) -> dict:
    """`approvers` are the active users who hold approval rights ({username, email, role}). Who can really be asked: they need an e-mail address
    and may not be the person who asked for the purchase (no self-approval). Returns {"eligible": [...], "reason": None | text}; a reason means
    the request cannot reach a normal approver and goes to the admins, who are told why. Admins count as approvers; the reason is raised when
    nobody BUT admins can be asked, so the admins know they are the only cover."""
    delegations: list[dict] = []
    if directory is not None and today is not None and any(on_leave(a, today) for a in approvers):
        effective = effective_approvers(approvers, directory, today)
        delegations = effective["delegations"]
        if not effective["askable"] and effective["unreachable"]:
            return {"eligible": [], "delegations": [], "reason": "Every approver is on leave and has no one to cover: " + ", ".join(effective["unreachable"]) + "."}
        approvers = effective["askable"]
    me = (requester or "").strip().lower()
    askable = [a for a in approvers if (a.get("email") or "").strip() and (a.get("username") or "").strip().lower() != me]
    if not approvers:
        return {"eligible": [], "delegations": delegations, "reason": "Nobody has the right to approve orders."}
    if not askable:
        if any((a.get("username") or "").strip().lower() == me for a in approvers) and len(approvers) == 1:
            return {"eligible": [], "delegations": delegations, "reason": "The only approver is the person who asked for this purchase, and nobody may approve their own request."}
        return {"eligible": [], "delegations": delegations, "reason": "None of the approvers has an e-mail address, so nobody could be asked."}
    if all(a.get("role") == ADMIN_ROLE for a in askable):
        return {"eligible": askable, "delegations": delegations, "reason": "No approver other than the admins can be asked (the others are missing, have no e-mail address, or asked for this themselves)."}
    return {"eligible": askable, "delegations": delegations, "reason": None}


# ---- Delivery: more than ordered, and goods before the order was confirmed ---------------------------------------------------------------------

def _key(name: str) -> str:
    return " ".join(str(name).lower().split())


def over_delivery(po_items: list[dict], outstanding: dict[str, int], incoming: dict[str, int] | None) -> list[dict]:
    """Lines where the quantity being received is MORE than is still owed: [{"description", "owed", "arrived", "extra"}]. `outstanding` is
    {item name (any case): still owed}. Items not on the order are ignored here (they are refused elsewhere). Nothing for 'receive all'."""
    if not incoming:
        return []
    owed = {_key(k): v for k, v in outstanding.items()}
    names = {_key(i["description"]): i["description"] for i in po_items}
    found = []
    for name, qty in incoming.items():
        k = _key(name)
        if k in names and isinstance(qty, int) and not isinstance(qty, bool) and qty > owed.get(k, 0):
            found.append({"description": names[k], "owed": owed.get(k, 0), "arrived": qty, "extra": qty - owed.get(k, 0)})
    return found


def over_delivery_text(lines: list[dict]) -> str:
    return "; ".join(f"{l['description']}: {l['arrived']} arrived, {l['owed']} still owed ({l['extra']} extra)" for l in lines)


# ---- Stock: what a case took off the shelf --------------------------------------------------------------------------------------------------

def stock_taken(events: list[dict]) -> dict[str, int]:
    """What the case took from stock, {stock item: quantity}, from its stock.checked event when that check was sufficient. Empty when nothing
    was taken, or when it has already been given back (stock.returned)."""
    if any(e["event_type"] == "stock.returned" for e in events):
        return {}
    taken: dict[str, int] = {}
    for e in events:
        payload = e.get("payload") or {}
        if e["event_type"] == "stock.checked" and payload.get("sufficient"):
            for c in payload.get("checks") or []:
                if c.get("stock_item") and c.get("requested"):
                    taken[c["stock_item"]] = taken.get(c["stock_item"], 0) + int(c["requested"])
    return taken


# ---- A user who has left ----------------------------------------------------------------------------------------------------------------------

def owned_open_cases(cases: list[dict], username: str) -> list[dict]:
    """Open cases this person asked for (they can no longer see or follow them)."""
    who = (username or "").strip().lower()
    return [c for c in cases if c.get("status") == "open" and (c.get("requester_id") or "").strip().lower() == who]


def left_text(display: str, cases: list[dict], limit: int = 10) -> str:
    lines = [f"  - {c.get('case_number') or c['case_id'][:8]}: {c.get('items_summary') or 'request'} (at '{str(c.get('stage')).replace('_', ' ')}')" for c in cases[:limit]]
    more = f"\n  ... and {len(cases) - limit} more" if len(cases) > limit else ""
    return f"{display} can no longer sign in, and asked for {len(cases)} request(s) that are still open:\n" + "\n".join(lines) + more
