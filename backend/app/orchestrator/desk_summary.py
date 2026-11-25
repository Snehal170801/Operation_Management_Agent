"""Sends each department its morning summary. Called by the worker every tick; does nothing unless it is switched on and due."""

import logging
from datetime import date, datetime, timezone

from app.clients import email_client
from app.controllers import my_work_controller
from app.core import desk_summary as rules
from app.core.config import settings
from app.core.permissions import DEPARTMENTS, ADMIN_ROLE
from app.repositories import automation_repository, user_repository

logger = logging.getLogger(__name__)
LAST_SENT_KEY = "desk_summary.last_sent"


def _last_sent() -> date | None:
    row = automation_repository.get_setting(LAST_SENT_KEY)
    try:
        return date.fromisoformat(row.setting_value) if row else None
    except ValueError:
        return None


def send_due(now: datetime | None = None) -> int:
    """Returns how many e-mails went out. A department with nothing waiting, or nobody with an address, is skipped."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if not rules.is_due(now, settings.DESK_SUMMARY_ENABLED, settings.DESK_SUMMARY_HOUR, _last_sent()):
        return 0
    # Claim the day first (one atomic statement): a crash half-way, a restart or a second copy of the app must not send everyone another copy.
    if not automation_repository.claim_setting(LAST_SENT_KEY, rules.today_ist(now).isoformat(), "desk summary"):
        return 0
    sent = 0
    for dept in DEPARTMENTS:
        permission = rules.DESK_PERMISSION[dept.key]
        people = [u for u in user_repository.find_active_users_with_permission(permission) if u.role != ADMIN_ROLE and u.email]
        if not people:
            continue
        try:
            work = my_work_controller.work_for("", lambda p, allowed=dept.permissions: p in allowed).model_dump()
            text = rules.body(dept.label, work, settings.APP_BASE_URL)
        except Exception:
            logger.exception("Could not build the morning summary for %s", dept.label)
            continue
        if text is None:
            continue
        title = rules.subject(dept.label, work["total"], rules.urgent_count(work))
        for person in people:
            try:
                email_client.send_email(person.email, title, text)
                sent += 1
            except Exception:
                logger.exception("Morning summary to %s failed", person.email)
    logger.info("Morning summaries sent: %s", sent)
    return sent
