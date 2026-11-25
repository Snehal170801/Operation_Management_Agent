"""Approver leave and the backup approver (delegate).

While a person is on leave, approvals that would be sent to them go to their delegate; if the delegate is unavailable too (on leave,
deactivated, no e-mail address, cannot approve) the next delegate along is tried, at most twice; with nobody left, the admins are told.
Pure functions over plain dicts and a date: no database, no clock, no e-mail.

A person: {user_id, username, email, role, active, can_approve, on_leave_from, on_leave_until, delegate_user_id}.
"""

from datetime import date

from app.core.exceptions import InvalidInput

MAX_HOPS = 2


def check_leave(on_leave_from: date | None, on_leave_until: date | None) -> None:
    """The dates a person may be given. One date alone is fine (from then on / until then); both must be in order."""
    if on_leave_from and on_leave_until and on_leave_until < on_leave_from:
        raise InvalidInput("The leave cannot end before it starts.")


def on_leave(person: dict, today: date) -> bool:
    start, end = person.get("on_leave_from"), person.get("on_leave_until")
    if start is None and end is None:
        return False
    return (start is None or start <= today) and (end is None or today <= end)


def _usable(person: dict | None, today: date) -> bool:
    return bool(person and person.get("active", True) and person.get("can_approve", True) and (person.get("email") or "").strip() and not on_leave(person, today))


def delegate_for(person: dict, directory: dict[str, dict], today: date) -> dict | None:
    """Who covers this person: their delegate, or the delegate's delegate when that one is away too. None when nobody can."""
    seen = {str(person.get("user_id")).lower()}
    current = person
    for _ in range(MAX_HOPS):
        key = str(current.get("delegate_user_id") or "").lower()
        if not key or key in seen:
            return None
        seen.add(key)
        candidate = directory.get(key)
        if _usable(candidate, today):
            return candidate
        if candidate is None or not candidate.get("active", True):
            return None
        current = candidate
    return None


def effective_approvers(approvers: list[dict], directory: dict[str, dict], today: date) -> dict:
    """Who is really asked today. {"askable": [...], "delegations": [{"from", "to"}], "unreachable": [usernames on leave with nobody to cover]}.
    An approver who is not on leave stays; one on leave is replaced by their delegate (once, even if two people name the same one)."""
    askable: dict[str, dict] = {}
    delegations: list[dict] = []
    unreachable: list[str] = []
    for person in approvers:
        if not on_leave(person, today):
            askable.setdefault(str(person["user_id"]).lower(), person)
            continue
        cover = delegate_for(person, directory, today)
        if cover is None:
            unreachable.append(person["username"])
            continue
        askable.setdefault(str(cover["user_id"]).lower(), cover)
        delegations.append({"from": person["username"], "to": cover["username"]})
    return {"askable": list(askable.values()), "delegations": delegations, "unreachable": unreachable}
