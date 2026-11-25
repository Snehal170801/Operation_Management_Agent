"""The weekly summary e-mail for the admins: what the system did this week and what is waiting.

Pure functions (the clock and the data come in as arguments). `orchestrator/weekly_summary` gathers the data and sends. One e-mail per
week, ever: the week it was sent for is remembered in the database BEFORE sending, so a restart or a second copy of the app cannot send it again.
"""

from datetime import date, datetime, timedelta, timezone

from app.core.desk_summary import IST

CATCH_UP_HOURS = 24            # a server that was down at the set time still sends, but not days later


def week_key(now_utc: datetime) -> str:
    """The Monday (India date) of the week `now_utc` falls in, as text: the identity of 'this week'."""
    local = now_utc.replace(tzinfo=timezone.utc).astimezone(IST).date()
    return (local - timedelta(days=local.weekday())).isoformat()


def is_due(now_utc: datetime, enabled: bool, weekday: int, hour: int, last_week: str | None) -> bool:
    """True from the set weekday and hour (India time; weekday 0 = Monday) for CATCH_UP_HOURS, once per week."""
    if not enabled or not (0 <= weekday <= 6) or not (0 <= hour <= 23):
        return False
    local = now_utc.replace(tzinfo=timezone.utc).astimezone(IST)
    key = week_key(now_utc)
    if last_week == key:
        return False
    monday = date.fromisoformat(key)
    start = datetime(monday.year, monday.month, monday.day, hour, tzinfo=IST) + timedelta(days=weekday)
    return start <= local < start + timedelta(hours=CATCH_UP_HOURS)


def _rs(value) -> str:
    return "-" if value is None else f"Rs {value:,.0f}"


def subject(report: dict) -> str:
    t = report["totals"]
    return f"Weekly summary: {t['requests']} request(s), {t['completed']} completed, {_rs(t['spend'])} ordered"


def body(report: dict, waiting: dict, base_url: str) -> str:
    """The e-mail text. `report` is core/reports.build_report for the last 7 days; `waiting` is {"total", "urgent", "by_department": [(name, n)]}."""
    t, a = report["totals"], report["automation"]
    lines = ["Here is last week in Operation Agents.", "",
             f"Requests: {t['requests']} started, {t['completed']} completed, {t['from_stock']} filled from stock, "
             f"{t['rejected']} not approved, {t['cancelled']} cancelled, {t['in_progress']} still open.",
             f"Orders placed: {t['orders']} worth {_rs(t['spend'])}."]
    if t.get("avg_cycle_hours") is not None:
        lines.append(f"Average time from request to completion: {t['avg_cycle_hours'] / 24:.1f} days.")
    if a.get("touchless_pct") is not None:
        lines.append(f"Handled with no person needed: {a['touchless_pct']}% ({a['touchless']} request(s)); {a['needed_a_person']} needed a person.")
    top = (report.get("spend") or {}).get("by_vendor") or []
    if top:
        lines.append("Most ordered from: " + ", ".join(f"{v['vendor']} ({_rs(v['total'])})" for v in top[:3]) + ".")
    lines.append("")
    stuck = report.get("stuck") or []
    if stuck:
        lines.append("Open requests, by where they are:")
        lines += [f"  - {s['label']}: {s['count']} (the oldest has been there {s['oldest_hours'] / 24:.1f} days)" for s in stuck[:6]]
        lines.append("")
    if waiting.get("total"):
        lines.append(f"Waiting for people right now: {waiting['total']}" + (f" ({waiting['urgent']} urgent)" if waiting.get("urgent") else ""))
        lines += [f"  - {name}: {n}" for name, n in waiting.get("by_department", []) if n]
        lines.append("")
    else:
        lines += ["Nothing is waiting for a person right now.", ""]
    lines += [f"Full report: {base_url}/reports", "", "An administrator can switch this e-mail off or change its day and time in Settings -> Configure."]
    return "\n".join(lines) + "\n"
