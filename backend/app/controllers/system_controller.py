import logging
import platform
import time
from datetime import datetime, timezone

from app.core import audit, automation, system_watch
from app.core.config import settings
from app.models.auth_schemas import CurrentUser
from app.models.system_schemas import AutomationResponse, HealthCheck, SystemHealthResponse, SystemInfo, SystemStats
from app.repositories import system_repository

logger = logging.getLogger("app.system")

_STARTED = time.time()
_SLOW_DB_MS = 500


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def get_health() -> SystemHealthResponse:
    checks: list[HealthCheck] = [
        HealthCheck(name="API", status="ok", detail="Serving requests"),
    ]
    stats = None
    server_version = None

    started = time.perf_counter()
    try:
        overview = system_repository.get_db_overview()
        latency = round((time.perf_counter() - started) * 1000, 1)
        server_version = overview["server_version"]
        stats = SystemStats(**{k: v for k, v in overview.items() if k != "server_version"})
        slow = latency > _SLOW_DB_MS
        checks.append(
            HealthCheck(
                name="Database",
                status="warning" if slow else "ok",
                detail="Responding slowly" if slow else "Connected",
                latency_ms=latency,
            )
        )
    except Exception:
        # Details go to the log; the response must not leak connection strings or server errors.
        logger.exception("health check: database unreachable")
        checks.append(HealthCheck(name="Database", status="down", detail="Cannot reach the database"))

    # Configuration check only: no paid API call on every poll.
    ai_ready = bool(settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT)
    checks.append(
        HealthCheck(
            name="Azure OpenAI",
            status="ok" if ai_ready else "warning",
            detail=f"Configured ({settings.AZURE_OPENAI_DEPLOYMENT_NAME})" if ai_ready else "Not configured",
        )
    )

    # Configuration checks only (no login on every poll; scripts/preflight does the real sign-in).
    # Without SMTP, emails are only written to the log yet the app still reports them as sent, so
    # this must be visible: a manager would otherwise believe a purchase order reached the supplier.
    smtp_ready = bool(settings.SMTP_HOST and (settings.SMTP_FROM or settings.SMTP_USER))
    checks.append(
        HealthCheck(
            name="Outgoing email",
            status="ok" if smtp_ready else "warning",
            detail=f"Sending via {settings.SMTP_HOST}" if smtp_ready
            else "Not configured: emails to suppliers and managers are only logged, NOT sent",
        )
    )
    imap_ready = bool(settings.IMAP_HOST and settings.IMAP_USER)
    checks.append(
        HealthCheck(
            name="Mailbox reader",
            status="ok" if imap_ready else "warning",
            detail=f"Reading {settings.IMAP_USER}" if imap_ready
            else "Not configured: supplier replies and invoices must be entered by hand",
        )
    )

    # The system's own background jobs: the follow-up worker and the instant mailbox watcher.
    for c in system_watch.current_checks():
        checks.append(HealthCheck(name=c.label, status=c.status, detail=c.detail))

    statuses = {c.status for c in checks}
    overall = "down" if "down" in statuses else "warning" if "warning" in statuses else "ok"

    return SystemHealthResponse(
        status=overall,
        checked_at=_iso(time.time()),
        checks=checks,
        info=SystemInfo(
            environment=settings.ENVIRONMENT,
            python_version=platform.python_version(),
            started_at=_iso(_STARTED),
            uptime_seconds=int(time.time() - _STARTED),
            database=settings.SQL_DATABASE,
            server_version=server_version,
        ),
        stats=stats,
    )


def _automation_response(state: automation.AutomationState) -> AutomationResponse:
    return AutomationResponse(
        paused=state.paused,
        updated_at=state.updated_at.isoformat() if state.updated_at else None,
        updated_by=state.updated_by,
    )


def get_automation() -> AutomationResponse:
    return _automation_response(automation.get_state())


def set_automation(paused: bool, user: CurrentUser) -> AutomationResponse:
    state = automation.set_paused(paused, user.username)
    audit.record(
        "automation.pause" if paused else "automation.resume",
        actor_user_id=user.user_id, actor_username=user.username,
        target_type="system", target_id="automation",
    )
    return _automation_response(state)
