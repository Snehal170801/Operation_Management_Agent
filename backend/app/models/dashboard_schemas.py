from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models.notification_schemas import NotificationResponse


class DashboardTotals(BaseModel):
    cases_total: int
    cases_open: int
    cases_closed: int
    pending_approvals: int
    needs_attention: int
    stock_items: int
    low_stock: int
    out_of_stock: int
    suppliers: int
    purchase_orders: int
    awaiting_delivery: int
    overdue_deliveries: int
    invoices_to_review: int


class StageCount(BaseModel):
    stage: str
    count: int


class DayCount(BaseModel):
    day: date
    count: int


class ActivityItem(BaseModel):
    event_id: int
    case_id: str
    case_number: Optional[str] = None
    event_type: str
    agent_name: Optional[str] = None
    created_at: datetime


class Spend(BaseModel):
    ordered_total: float
    ordered_today: float
    auto_approved_today: float
    daily_limit: float


class Rates(BaseModel):
    # Share of decided approvals that policy made without a person (0-100), or None if there are none yet.
    auto_approval_percent: Optional[float] = None
    avg_close_minutes: Optional[float] = None


class DashboardSnapshot(BaseModel):
    generated_at: datetime
    automation_paused: bool
    totals: DashboardTotals
    by_stage: list[StageCount]
    created_per_day: list[DayCount]
    activity: list[ActivityItem]
    attention: list[NotificationResponse]
    spend: Spend
    rates: Rates
