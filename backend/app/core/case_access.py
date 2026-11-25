"""Who may see which case, and how much of it.

Staff (`cases:read_all`) see every case in full. A requester (`cases:read` only) sees just the
cases they submitted, and only the agent flow -- never the internals (prices, vendor names,
reliability scores, approval reasons, errors). This is enforced here on the server; hiding
menus in the UI is not security.
"""

from app.core import access
from app.core.exceptions import CaseNotFound
from app.models.auth_schemas import CurrentUser
from app.repositories import case_repository

VIEW_ALL = "cases:read_all"

# Events a requester may see (type only -- the payload is always dropped). Anything not listed,
# e.g. notifications, worker errors, ignored emails, reminders and stage.* noise, stays internal.
_REQUESTER_VISIBLE_EVENTS = frozenset({
    "case.created",
    "purchase_request.created",
    "stock.checked",
    "rfq.sent",
    "quote.submitted",
    "vendor.selected",
    "approval.requested",
    "approval.auto_approved",
    "approval.approved",
    "approval.rejected",
    "sourcing.restarted",
    "po.issued",
    "delivery.received",
    "delivery.partial",
    "goods.issue_reported",
    "goods.issue_resolved",
    "request.changed",
    "case.cancelled",
    "case.merged_into",
    "po.cancel_requested",
    "po.cancelled",
    "po.cancel_withdrawn",
    "case.closed",
    "document.received",           # a supplier's document is being read (type only: no name, no content)
    "document.reading",
    "document.read",
})


def can_view_all(user: CurrentUser) -> bool:
    return access.has_permission(user.role, VIEW_ALL)


def assert_can_view(user: CurrentUser, case_id: str) -> None:
    """Raises CaseNotFound (404, never 403, so case ids can't be probed) unless the user may see this case."""
    if can_view_all(user):
        return
    row = case_repository.find_case_by_id(case_id)
    if row is None or row.requester_id.strip().lower() != user.username.strip().lower():
        raise CaseNotFound(case_id)


def requester_filter(user: CurrentUser) -> str | None:
    """The requester_id to restrict listings to, or None for staff (everything)."""
    return None if can_view_all(user) else user.username


def visible_events(events: list[dict], user: CurrentUser) -> list[dict]:
    if can_view_all(user):
        return events
    return [
        {**e, "payload": None}
        for e in events
        if e["event_type"] in _REQUESTER_VISIBLE_EVENTS
    ]
