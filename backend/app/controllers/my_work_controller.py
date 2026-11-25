from datetime import datetime, timedelta, timezone

from app.agents import approval_agent, delivery_agent, invoice_agent, operations_agent, procurement_agent, purchase_order_agent, vendor_agent
from app.core import access
from app.controllers.invoice_suggestions import attach_suggestions
from app.core.config import settings
from app.core.handled import HANDLED_EVENTS
from app.core.my_work import build_my_work
from app.models.auth_schemas import CurrentUser
from app.models.my_work_schemas import MyWork
from app.orchestrator import case_pipeline

_CASE_QUEUES = ("approvals:write", "delivery:confirm", "invoices:decide", "vendors:write", "po:manage", "cases:write")


def get_my_work(user: CurrentUser) -> MyWork:
    """What is waiting on the signed-in person, from only the data their own jobs need."""
    return work_for(user.username, lambda permission: access.has_permission(user.role, permission))


def work_for(username: str, can) -> MyWork:
    """The same picture for anyone, given what they (or a whole department) may do. The morning summary uses it too."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cases = operations_agent.get_all_cases(None) if any(can(p) for p in _CASE_QUEUES) else []
    return MyWork(**build_my_work(
        username, can, now=now, cases=cases, escalate_after_hours=settings.ESCALATE_AFTER_HOURS,
        chase_hours=settings.INVOICE_CHASE_HOURS, max_chases=settings.INVOICE_MAX_CHASES,
        approvals=approval_agent.get_approvals(status="pending") if can("approvals:write") else [],
        deliveries=delivery_agent.get_open_deliveries() if can("delivery:confirm") else [],
        invoices=attach_suggestions(invoice_agent.list_invoices()) if can("invoices:decide") else [],
        stock=procurement_agent.get_all_stock() if can("stock:write") else [],
        disputes=delivery_agent.get_open_disputes() if can("delivery:confirm") else {},
        goods_issues=delivery_agent.get_open_issues() if can("delivery:confirm") else [],
        bounced_vendors=[v for v in vendor_agent.get_all_vendors() if v.get("email_bounced_at")] if can("vendors:write") else [],
        combine_suggestions=case_pipeline.combine_suggestions() if can("vendors:write") and settings.COMBINE_SUGGESTIONS else [],
        handled_events=operations_agent.get_events_of_types(tuple(HANDLED_EVENTS), now - timedelta(hours=settings.HANDLED_HOURS)) if cases else [],
        handled_hours=settings.HANDLED_HOURS,
        po_alerts=purchase_order_agent.get_confirmation_alerts() if can("po:manage") else [],
    ))
