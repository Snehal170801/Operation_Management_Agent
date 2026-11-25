import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from app.core.agent_steps import STEP_FAILED, STEP_FINISHED, STEP_PROGRESS, STEP_STARTED, STEPS, Step
from app.core.exceptions import CaseNotFound
from app.repositories import case_repository

logger = logging.getLogger(__name__)


def create_case(requester_id: str) -> str:
    case_id = str(uuid.uuid4())
    case_repository.insert_case(case_id, requester_id)
    publish_event(case_id, "case.created", agent_name="Operations Agent",
                  payload={"requester_id": requester_id})
    return case_id


def get_case_status(case_id: str) -> dict:
    row = case_repository.find_case_by_id(case_id)
    if row is None:
        raise CaseNotFound(case_id)
    return {
        "case_id": str(row.case_id),
        "case_number": row.case_number,
        "requester_id": row.requester_id,
        "stage": row.stage,
        "status": row.status,
        "summary": row.summary,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def get_all_cases(requester_id: str | None = None) -> list[dict]:
    rows = case_repository.find_all_cases(requester_id)
    return [
        {
            "case_id": str(row.case_id),
            "case_number": row.case_number,
            "requester_id": row.requester_id,
            "stage": row.stage,
            "status": row.status,
            "item_count": row.item_count,
            "total_quantity": row.total_quantity,
            "items_summary": row.items_summary,
            "urgent": bool(getattr(row, "urgent", 0) or 0),
            "needed_by": getattr(row, "needed_by", None),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


def set_stage(case_id: str, stage: str) -> None:
    case_repository.update_case_stage(case_id, stage)
    publish_event(case_id, f"stage.{stage}", agent_name="Operations Agent")


def close_case(case_id: str, stage: str, reason: str) -> None:
    case_repository.update_case_stage_and_status(case_id, stage, "closed")
    publish_event(case_id, "case.closed", agent_name="Operations Agent",
                  payload={"stage": stage, "reason": reason})


def find_recent_duplicate(requester_id: str, raw_request: str, minutes: int) -> str | None:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    return case_repository.find_recent_duplicate(requester_id, raw_request, since)


def find_idle_cases(stage: str, minutes: int) -> list[str]:
    idle_since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
    return case_repository.find_open_case_ids_by_stage(stage, idle_since)


def count_recent_cases(requester_id: str, hours: int = 24) -> int:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    return case_repository.count_cases_since(requester_id, since)


def publish_event(case_id: str, event_type: str, agent_name: str = None, payload: dict = None) -> None:
    case_repository.insert_event(case_id, event_type, agent_name, payload)


# ---------------------------------------------------------------------------------------------
# Live "what is each agent doing right now" signals (see app/core/agent_steps.py)

_current_step: ContextVar["StepTracker | None"] = ContextVar("current_step", default=None)


def _signal(case_id: str, event_type: str, step: Step, payload: dict) -> None:
    """Record a step signal. These are for display only, so a failure to write one must never break
    the real work it describes: it is logged and swallowed."""
    try:
        case_repository.insert_event(case_id, event_type, step.agent, payload)
    except Exception:
        logger.warning("could not record %s for case %s", event_type, case_id, exc_info=True)


class StepTracker:
    def __init__(self, case_id: str, step: Step, run: str):
        self.case_id, self.step, self.run = case_id, step, run

    def progress(self, done: int, total: int, text: str | None = None) -> None:
        _signal(self.case_id, STEP_PROGRESS, self.step,
                {"step": self.step.key, "run": self.run, "done": done, "total": total, "text": text})


@contextmanager
def working(case_id: str, step_key: str, detail: str | None = None):
    """Mark an agent as working on a step for the duration of the block:

        with operations_agent.working(case_id, "check_stock"):
            procurement_agent.check_stock(case_id)

    Records step.started, then step.finished (with how long it took) or step.failed (and re-raises).
    `detail` is extra wording for staff only."""
    step = STEPS[step_key]
    run = uuid.uuid4().hex[:8]  # pairs a start with its finish when the same step happens more than once
    began = time.monotonic()
    base = {"step": step.key, "run": run}
    _signal(case_id, STEP_STARTED, step, {**base, "label": step.label, "detail": detail})

    tracker = StepTracker(case_id, step, run)
    token = _current_step.set(tracker)
    try:
        yield tracker
    except Exception as exc:
        _signal(case_id, STEP_FAILED, step, {**base, "error": str(exc)[:200]})
        raise
    else:
        _signal(case_id, STEP_FINISHED, step, {**base, "seconds": round(time.monotonic() - began, 1)})
    finally:
        _current_step.reset(token)


def step_active() -> bool:
    """True inside a `working(...)` block. Lets code skip work whose only purpose is a progress message."""
    return _current_step.get() is not None


def report_progress(done: int, total: int, text: str | None = None) -> None:
    """For code running inside `working(...)`: say how far along it is ("2 of 3"). Does nothing when no
    step is active, so agents can call it freely (and tests that call an agent directly are unaffected)."""
    tracker = _current_step.get()
    if tracker is not None:
        tracker.progress(done, total, text)


def _parse_payload(raw):
    """Events are stored as JSON text; hand callers the object (and tolerate rows that are not valid JSON)."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


def get_events_of_types(event_types: tuple[str, ...], since=None) -> list[dict]:
    """Events of the given kinds across all cases (for queues that span cases)."""
    return [
        {"case_id": str(r.case_id), "event_type": r.event_type, "payload": _parse_payload(r.payload), "created_at": r.created_at}
        for r in case_repository.find_events_of_types(event_types, since)
    ]


def get_case_events(case_id: str) -> list[dict]:
    rows = case_repository.find_events_by_case_id(case_id)
    return [
        {
            "event_id": row.event_id,
            "event_type": row.event_type,
            "agent_name": row.agent_name,
            "payload": _parse_payload(row.payload),
            "created_at": row.created_at,
        }
        for row in rows
    ]
