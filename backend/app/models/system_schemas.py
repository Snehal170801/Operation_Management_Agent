from typing import Literal, Optional

from pydantic import BaseModel

CheckStatus = Literal["ok", "warning", "down"]


class AutomationResponse(BaseModel):
    paused: bool
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class SetAutomationRequest(BaseModel):
    paused: bool


class HealthCheck(BaseModel):
    name: str
    status: CheckStatus
    detail: str
    latency_ms: Optional[float] = None


class SystemInfo(BaseModel):
    environment: str
    python_version: str
    started_at: str
    uptime_seconds: int
    database: str
    server_version: Optional[str] = None


class SystemStats(BaseModel):
    users: int
    active_sessions: int
    cases: int
    open_cases: int
    migrations_applied: int


class SystemHealthResponse(BaseModel):
    status: CheckStatus
    checked_at: str
    checks: list[HealthCheck]
    info: SystemInfo
    stats: Optional[SystemStats] = None
