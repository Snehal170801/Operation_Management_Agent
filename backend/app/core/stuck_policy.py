"""The general "stuck too long" check: every open case stage has a longest quiet time. A case that stays quiet past it is a problem nobody
noticed, so the right department is told once; if it is still quiet after a second limit the admin is told once. Moving the case on (any
stage change) starts it afresh.

Pure functions: the clock and the data come in as arguments. "Quiet" is the time since the case last changed stage (Cases.updated_at only
moves on a stage change, so reminders and chasers do not make a stuck case look alive). Telling people is the pipeline's job."""

from datetime import datetime, timedelta

# stage -> (kind of limit, department asked first). The department keys are those of core/permissions.ALERT_PERMISSION; None = the admins.
#   automatic: should move within minutes by itself, so a long wait means something broke
#   person:    waiting on a person (or on a failed step a person must fix)
#   waiting:   waiting on the outside world (a supplier, a delivery, an invoice), which has its own reminders; this is the last safety net
STAGES: dict[str, tuple[str, str | None]] = {
    "created": ("automatic", None),
    "purchase_request_created": ("automatic", None),
    "sourcing_needed": ("automatic", "vendor"),
    "vendor_selected": ("automatic", "approval"),
    "approved": ("automatic", "po"),
    "sourcing_stalled": ("person", "vendor"),
    "awaiting_approval": ("person", "approval"),
    "po_send_failed": ("person", "po"),
    "po_failed": ("person", "po"),
    "cancel_pending": ("person", "po"),
    "delivery_late": ("person", "delivery"),
    "awaiting_quotes": ("waiting", "vendor"),
    "negotiating": ("person", "vendor"),                  # it has its own timer (NEGOTIATE_WAIT_HOURS); this is the safety net
    "po_issued": ("waiting", "delivery"),
    "delivered": ("waiting", "invoice"),
}

STUCK_EVENT = "case.stuck"
ESCALATED_EVENT = "case.stuck_escalated"


def limits(automatic_hours: float, person_hours: float, waiting_hours: float) -> dict[str, float]:
    return {"automatic": automatic_hours, "person": person_hours, "waiting": waiting_hours}


def quiet_hours(now: datetime, case: dict) -> float:
    return max((now - case["updated_at"]).total_seconds() / 3600, 0.0)


def candidates(now: datetime, cases: list[dict], hours: dict[str, float]) -> list[dict]:
    """Open cases quiet for longer than their stage's limit (a limit of 0 switches that kind off). Oldest first.
    Each: case_id, case_number, stage, team, quiet_hours, limit_hours."""
    found = []
    for c in cases:
        rule = STAGES.get(c["stage"])
        if c["status"] != "open" or rule is None or hours.get(rule[0], 0) <= 0:
            continue
        quiet = quiet_hours(now, c)
        if quiet >= hours[rule[0]]:
            found.append({"case_id": c["case_id"], "case_number": c.get("case_number"), "summary": c.get("items_summary"), "stage": c["stage"],
                          "team": rule[1], "quiet_hours": round(quiet, 1), "limit_hours": hours[rule[0]]})
    return sorted(found, key=lambda f: -f["quiet_hours"])


def already_done(events: list[dict], since: datetime) -> set[str]:
    """What has been done for this case since it last moved: {"notified", "escalated", "admin_told"}. Events from before the last stage
    change are about an earlier episode and do not count, so a case that moves and sticks again is told about again.
    `admin_told` means the older escalation rule has already told the admin about this episode (no second mail)."""
    done: set[str] = set()
    for e in events:
        if e["created_at"] < since:
            continue
        if e["event_type"] == STUCK_EVENT:
            done.add("notified")
        elif e["event_type"] == ESCALATED_EVENT:
            done.add("escalated")
        elif e["event_type"] == "escalation.sent":
            done.add("admin_told")
    return done


def next_step(item: dict, done: set[str], escalate_after_hours: float) -> str | None:
    """"notify" (first time over the limit), "escalate" (still quiet `escalate_after_hours` after the limit, admin not yet told), or None.
    Never both at once and never the same one twice. A 0 for `escalate_after_hours` means the admin is not escalated to."""
    if "notified" not in done:
        return "notify"
    if escalate_after_hours > 0 and "escalated" not in done and "admin_told" not in done \
            and item["quiet_hours"] >= item["limit_hours"] + escalate_after_hours:
        return "escalate"
    return None
