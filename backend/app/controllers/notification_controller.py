import time
from datetime import datetime, timezone

from app.agents import approval_agent, invoice_agent, operations_agent
from app.core import access, case_access, system_watch
from app.core.notification_feed import requester_items, staff_items
from app.models.auth_schemas import CurrentUser
from app.models.notification_schemas import NotificationResponse


def list_notifications(user: CurrentUser) -> list[NotificationResponse]:
    if case_access.can_view_all(user):
        can_see_approvals = access.has_permission(user.role, "approvals:read")
        items = staff_items(
            approval_agent.get_approvals(status="pending") if can_see_approvals else [],
            operations_agent.get_all_cases(None),
            invoice_agent.list_invoices("mismatch"),
            can=lambda permission: access.has_permission(user.role, permission),
        )
    else:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        items = requester_items(operations_agent.get_all_cases(user.username), now)
    if access.has_permission(user.role, "system:write"):
        items = _system_items() + items
    return [NotificationResponse(**i) for i in items]


def _system_items() -> list[dict]:
    """For admins: a background job that has gone quiet is the most urgent thing in the bell."""
    now = time.time()
    out = []
    for c in system_watch.current_checks(now):
        if c.status == "ok":
            continue
        since = system_watch.watch.since(c.key, now)
        out.append({
            "id": f"system:{c.key}", "kind": "system", "requires_action": True, "title": f"{c.label} needs attention",
            "link": "/settings", "message": c.detail,
            "created_at": datetime.fromtimestamp(since, tz=timezone.utc).replace(tzinfo=None),
        })
    return out
