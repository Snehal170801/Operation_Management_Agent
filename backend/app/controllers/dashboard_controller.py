from datetime import date, datetime, timedelta, timezone

from app.agents import approval_agent, invoice_agent
from app.core import access, automation
from app.core.config import settings
from app.core.notification_feed import staff_items
from app.models.auth_schemas import CurrentUser
from app.models.dashboard_schemas import (
    ActivityItem,
    DashboardSnapshot,
    DashboardTotals,
    DayCount,
    Rates,
    Spend,
    StageCount,
)
from app.models.notification_schemas import NotificationResponse
from app.repositories import dashboard_repository, purchase_order_repository

TREND_DAYS = 7


def get_snapshot(user: CurrentUser) -> DashboardSnapshot:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    totals = dashboard_repository.totals(midnight)

    # What needs a person: same rules as the bell, so the two never disagree.
    can_see_approvals = access.has_permission(user.role, "approvals:read")
    pending = approval_agent.get_approvals(status="pending") if can_see_approvals else []
    cases = [
        {"case_id": str(r.case_id), "stage": r.stage, "status": r.status, "updated_at": r.updated_at,
         "items_summary": r.items_summary}
        for r in dashboard_repository.attention_cases()
    ]
    attention = staff_items(pending, cases, invoice_agent.list_invoices("mismatch"))

    auto, human = dashboard_repository.approval_split()
    decided = auto + human

    return DashboardSnapshot(
        generated_at=now,
        automation_paused=automation.is_paused(),
        totals=DashboardTotals(**{k: v for k, v in totals.items() if k not in ("ordered_total", "ordered_today")},
                               needs_attention=len(attention)),
        by_stage=[StageCount(stage=s, count=n) for s, n in dashboard_repository.by_stage()],
        created_per_day=_fill_days(dashboard_repository.created_per_day(midnight - timedelta(days=TREND_DAYS - 1)),
                                   midnight.date()),
        activity=[
            ActivityItem(event_id=r.event_id, case_id=str(r.case_id), case_number=getattr(r, "case_number", None), event_type=r.event_type,
                         agent_name=r.agent_name, created_at=r.created_at)
            for r in dashboard_repository.recent_activity()
        ],
        attention=[NotificationResponse(**i) for i in attention],
        spend=Spend(
            ordered_total=totals["ordered_total"], ordered_today=totals["ordered_today"],
            auto_approved_today=purchase_order_repository.sum_auto_approved_since(midnight),
            daily_limit=settings.AUTO_APPROVE_DAILY_LIMIT,
        ),
        rates=Rates(
            auto_approval_percent=round(100 * auto / decided, 1) if decided else None,
            avg_close_minutes=dashboard_repository.average_close_minutes(),
        ),
    )


def _fill_days(rows: list[tuple], today: date) -> list[DayCount]:
    """One entry for each of the last TREND_DAYS days, with 0 where nothing happened."""
    counts = {day: n for day, n in rows}
    return [DayCount(day=today - timedelta(days=i), count=counts.get(today - timedelta(days=i), 0))
            for i in range(TREND_DAYS - 1, -1, -1)]
