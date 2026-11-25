from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReportTotals(BaseModel):
    requests: int
    completed: int
    from_stock: int
    rejected: int
    cancelled: int = 0
    in_progress: int
    spend: float
    orders: int
    avg_cycle_hours: Optional[float] = None


class ReasonCount(BaseModel):
    label: str
    cases: int


class AgentTrouble(BaseModel):
    agent: str
    cases: int
    reasons: list[ReasonCount]


class ReportAutomation(BaseModel):
    touchless: int
    needed_a_person: int
    in_progress_so_far_clean: int
    touchless_pct: Optional[int] = None
    by_agent: list[AgentTrouble]


class VendorSpend(BaseModel):
    vendor: str
    total: float
    orders: int


class MonthSpend(BaseModel):
    month: str
    total: float
    orders: int


class ReportSpend(BaseModel):
    total: float
    orders: int
    by_vendor: list[VendorSpend]
    by_month: list[MonthSpend]


class StageTime(BaseModel):
    label: str
    avg_hours: Optional[float] = None
    count: int


class StuckStage(BaseModel):
    stage: str
    label: str
    count: int
    oldest_hours: float
    avg_hours: float


class SupplierScore(BaseModel):
    vendor_id: str
    name: str
    asked: int
    replied: int
    reply_rate: Optional[int] = None
    avg_reply_hours: Optional[float] = None
    orders: int
    spend: float
    confirm_rate: Optional[int] = None
    avg_confirm_hours: Optional[float] = None
    delivered: int
    late: int
    avg_days_late: Optional[float] = None
    invoices: int
    invoice_problems: int


class Report(BaseModel):
    days: int
    generated_at: datetime
    totals: ReportTotals
    automation: ReportAutomation
    spend: ReportSpend
    stage_times: list[StageTime]
    stuck: list[StuckStage]
    suppliers: list[SupplierScore]
