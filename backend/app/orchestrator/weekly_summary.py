"""Sends the admins their weekly summary. Called by the worker every tick; does nothing unless it is switched on and due."""

import logging
from datetime import datetime, timezone

from app.clients import email_client
from app.controllers import my_work_controller, report_controller
from app.core import weekly_summary as rules
from app.core.config import settings
from app.core.permissions import DEPARTMENTS
from app.repositories import automation_repository, user_repository

logger = logging.getLogger(__name__)
LAST_SENT_KEY = "weekly_summary.last_week"
ADMIN_PERMISSION = "system:write"


def _last_week() -> str | None:
    row = automation_repository.get_setting(LAST_SENT_KEY)
    return row.setting_value if row else None


def _waiting() -> dict:
    """What is waiting for people right now, per department (the same lists as My work). A department that cannot be read is left out."""
    by_department, total, urgent = [], 0, 0
    for dept in DEPARTMENTS:
        try:
            work = my_work_controller.work_for("", lambda p, allowed=dept.permissions: p in allowed).model_dump()
        except Exception:
            logger.exception("Could not read the waiting work of %s for the weekly summary", dept.label)
            continue
        n = sum(len(q["items"]) for q in work["queues"])
        urgent += sum(1 for q in work["queues"] for i in q["items"] if i["urgent"])
        total += n
        by_department.append((dept.label, n))
    return {"total": total, "urgent": urgent, "by_department": by_department}


def send_due(now: datetime | None = None) -> int:
    """Returns how many e-mails went out (0 when not due, switched off, already sent for this week, or nobody to send to)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if not rules.is_due(now, settings.WEEKLY_SUMMARY_ENABLED, settings.WEEKLY_SUMMARY_DAY, settings.WEEKLY_SUMMARY_HOUR, _last_week()):
        return 0
    admins = [u for u in user_repository.find_active_users_with_permission(ADMIN_PERMISSION) if u.email]
    if not admins:
        logger.warning("The weekly summary is due but no admin has an e-mail address")
        return 0
    # Claim the week first (one atomic statement): a crash half-way, a restart or a second copy of the app must not send it again.
    if not automation_repository.claim_setting(LAST_SENT_KEY, rules.week_key(now), "weekly summary"):
        return 0
    try:
        report = report_controller.get_report(7).model_dump()
        text = rules.body(report, _waiting(), settings.APP_BASE_URL)
        title = rules.subject(report)
    except Exception:
        logger.exception("Could not build the weekly summary")
        return 0
    sent = 0
    for admin in admins:
        try:
            email_client.send_email(admin.email, title, text)
            sent += 1
        except Exception:
            logger.exception("Weekly summary to %s failed", admin.email)
    logger.info("Weekly summaries sent: %s", sent)
    return sent
