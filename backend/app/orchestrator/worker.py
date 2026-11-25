"""
Background loop that moves cases forward without anyone pressing a button.
Each tick looks at every open case waiting on vendor quotes and lets the pipeline
decide what to do (chase vendors, rank, or flag for a human).

Runs inside the API process. If several instances run, only the one holding the database lease
works (see automation.acquire_worker_lease); the others stay idle. A pause switch stops it entirely.
"""

import asyncio
import logging
import threading
import time

from app.agents import notification_agent, operations_agent
from app.clients import imap_client
from app.core import automation, heartbeat, system_watch, tunables
from app.core.config import settings
from app.orchestrator import case_pipeline, desk_summary, weekly_summary
from app.repositories import case_repository

logger = logging.getLogger(__name__)

AWAITING_QUOTES = "awaiting_quotes"

# Mail is read from two places: the instant path (the server says "new mail") and the once-a-minute tick.
# One lock keeps them from ever working on the same message at once.
_mail_lock = threading.Lock()
MAIL_LOCK_WAIT_SECONDS = 120
IDLE_SECONDS = 9 * 60  # Gmail drops an idle connection after ~10 minutes, so renew before that


def read_mailbox() -> int:
    """Read and handle any unread vendor mail right now."""
    # Never wait for the lock forever: if one read hangs, the others give up after a while instead of freezing the worker too.
    if not _mail_lock.acquire(timeout=MAIL_LOCK_WAIT_SECONDS):
        logger.warning("Another mailbox read has held the lock for over %ss; skipping this one", MAIL_LOCK_WAIT_SECONDS)
        return 0
    try:
        senders = case_pipeline.supplier_addresses()
        if senders:
            return imap_client.process_unseen_replies(case_pipeline.ingest_quote_email, senders)
        return imap_client.process_unseen_replies(case_pipeline.ingest_quote_email)
    finally:
        _mail_lock.release()


def react_to_new_mail() -> int:
    """The instant path: same rules as a worker tick (paused, or not the instance holding the lease, means hands off)."""
    if automation.is_paused():
        return 0
    if not automation.acquire_worker_lease(max(120, settings.WORKER_INTERVAL_SECONDS * 3)):
        return 0
    return read_mailbox()


def run_once() -> None:
    if automation.is_paused():
        logger.info("Automation is paused; the worker is idle")
        return
    # Only one instance may run the loop; others stay idle until its lease lapses.
    if not automation.acquire_worker_lease(max(120, settings.WORKER_INTERVAL_SECONDS * 3)):
        return

    # Read vendor replies first so this tick already sees any new quotes.
    try:
        read_mailbox()
    except Exception:
        logger.exception("Reading the vendor mailbox failed")

    for case_id in case_repository.find_open_case_ids_by_stage(AWAITING_QUOTES):
        try:
            case_pipeline.advance_sourcing(case_id)
        except Exception as exc:
            # Don't retry a failing case forever (each retry may cost an LLM call): park it for a human.
            logger.exception("Worker failed on case %s", case_id)
            operations_agent.publish_event(
                case_id, "worker.error", agent_name="Worker", payload={"error": str(exc)},
            )
            operations_agent.set_stage(case_id, "sourcing_stalled")
            notification_agent.notify_case_stalled(case_id, f"An automatic step failed: {exc}")

    try:
        case_pipeline.resume_held_cases()
    except Exception:
        logger.exception("Resuming held cases failed")

    try:
        case_pipeline.remind_pending_approvals()
    except Exception:
        logger.exception("Approval reminders failed")

    try:
        case_pipeline.track_deliveries()
    except Exception:
        logger.exception("Delivery tracking failed")

    try:
        case_pipeline.track_po_confirmations()
    except Exception:
        logger.exception("Tracking order confirmations failed")

    try:
        case_pipeline.track_cancellations()
    except Exception:
        logger.exception("Tracking order cancellations failed")

    try:
        case_pipeline.track_goods_issues()
    except Exception:
        logger.exception("Tracking goods problems failed")

    try:
        case_pipeline.chase_invoice_corrections()
    except Exception:
        logger.exception("Chasing corrected invoices failed")

    try:
        case_pipeline.escalate_overdue()
    except Exception:
        logger.exception("Escalation failed")

    try:
        case_pipeline.track_negotiations()
    except Exception:
        logger.exception("Tracking the requests for a better price failed")

    try:
        case_pipeline.auto_reorder_low_stock()
    except Exception:
        logger.exception("The automatic reorder check failed")

    try:
        case_pipeline.sweep_stuck_cases()
    except Exception:
        logger.exception("The stuck-case sweep failed")

    try:
        weekly_summary.send_due()
    except Exception:
        logger.exception("The weekly summary failed")

    try:
        desk_summary.send_due()
    except Exception:
        logger.exception("Morning summaries failed")


async def run_forever() -> None:
    logger.info("Sourcing worker started (every %ss)", settings.WORKER_INTERVAL_SECONDS)
    while True:
        heartbeat.beat(heartbeat.WORKER)  # still going round (the health monitor tells an admin if this stops)
        try:
            # Every copy of the app follows what is saved, whether or not it holds the worker lease.
            await asyncio.to_thread(tunables.refresh)
        except Exception:
            logger.exception("Reloading the saved configuration failed")
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("Worker tick failed")
        heartbeat.beat(heartbeat.WORKER)
        await asyncio.sleep(settings.WORKER_INTERVAL_SECONDS)


async def watch_mailbox_forever() -> None:
    """Keep a line open to the mailbox and react the moment mail arrives (a vendor's reply is then read in
    seconds, not at the next minute). Anything that goes wrong just retries; the once-a-minute tick is the backup."""
    if not settings.IMAP_HOST:
        return
    logger.info("Instant mailbox watcher started")
    heartbeat.beat(heartbeat.MAILBOX)  # alive; a failed attempt below counts against it until one succeeds
    while True:
        try:
            arrived = await asyncio.to_thread(imap_client.wait_for_new_mail, IDLE_SECONDS)
            heartbeat.beat(heartbeat.MAILBOX)
            if arrived:
                await asyncio.to_thread(react_to_new_mail)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Instant mailbox watcher failed; retrying shortly")
            heartbeat.fail(heartbeat.MAILBOX, exc)
            await asyncio.sleep(15)
        await asyncio.sleep(1)  # never a hot loop, whatever the server does


HEALTH_CHECK_SECONDS = 60


def announce(events: list[system_watch.Event]) -> None:
    for e in events:
        since = time.strftime("%d %b %H:%M", time.localtime(e.since))
        try:
            sent = notification_agent.notify_system(e.kind, e.check.label, e.check.detail, since)
            logger.warning("System %s: %s (%s); %s admin(s) emailed", e.kind, e.check.label, e.check.detail, sent)
        except Exception:
            logger.exception("Could not announce the %s of %s", e.kind, e.check.label)


async def watch_health_forever() -> None:
    """Once a minute, look at the heartbeats and tell the admins if a background job has gone quiet."""
    logger.info("Health monitor started (every %ss)", HEALTH_CHECK_SECONDS)
    while True:
        try:
            events = system_watch.watch.step(system_watch.current_checks(), time.time())
            if events:
                await asyncio.to_thread(announce, events)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Health monitor failed")
        await asyncio.sleep(HEALTH_CHECK_SECONDS)
