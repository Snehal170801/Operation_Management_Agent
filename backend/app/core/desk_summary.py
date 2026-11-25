"""The morning summary e-mail for each department: what is waiting on it today.

Pure functions (the clock and the data come in as arguments). The worker decides when, `orchestrator/desk_summary` gathers the data and
sends. A department with nothing waiting gets no e-mail: a summary that says "nothing" every day teaches people to ignore it."""

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
CATCH_UP_HOURS = 6            # a server that was down at the set time still sends, but not hours later: it is a MORNING e-mail
SHOWN_PER_QUEUE = 5

# the people who get a department's summary: whoever holds the permission that marks them as that department (see core/permissions.py)
DESK_PERMISSION = {"purchase": "cases:write", "procurement": "stock:write", "vendor": "vendors:write", "approval": "approvals:write",
                   "po": "po:manage", "delivery": "delivery:confirm", "invoice": "invoices:decide"}


def today_ist(now_utc: datetime) -> date:
    return now_utc.replace(tzinfo=timezone.utc).astimezone(IST).date()


def is_due(now_utc: datetime, enabled: bool, hour: int, last_sent: date | None) -> bool:
    """True from the set hour (India time) until CATCH_UP_HOURS later, once per day."""
    if not enabled:
        return False
    local = now_utc.replace(tzinfo=timezone.utc).astimezone(IST)
    if last_sent == local.date():
        return False
    start = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    return start <= local < start + timedelta(hours=CATCH_UP_HOURS)


def subject(department: str, total: int, urgent: int) -> str:
    return f"{department}: {total} waiting for you today" + (f" ({urgent} urgent)" if urgent else "")


def body(department: str, work: dict, base_url: str) -> str | None:
    """The e-mail text, or None when nothing is waiting. `work` is what My work shows this department."""
    queues = [q for q in work["queues"] if q["items"]]
    if not queues:
        return None
    lines = [f"Good morning. This is what is waiting for {department} today.", ""]
    for q in queues:
        lines.append(f"{q['title']} ({len(q['items'])})")
        for item in q["items"][:SHOWN_PER_QUEUE]:
            lines.append(f"  - {'URGENT: ' if item['urgent'] else ''}{item['title']}")
            if item.get("detail"):
                lines.append(f"    {item['detail']}")
        if len(q["items"]) > SHOWN_PER_QUEUE:
            lines.append(f"  ... and {len(q['items']) - SHOWN_PER_QUEUE} more")
        lines.append("")
    lines += [f"Open My work: {base_url}/my-work", "", "An administrator can switch this e-mail off or change its time in Settings -> Configure."]
    return "\n".join(lines) + "\n"


def urgent_count(work: dict) -> int:
    return sum(1 for q in work["queues"] for i in q["items"] if i["urgent"])
