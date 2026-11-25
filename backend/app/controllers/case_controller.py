from app.agents import operations_agent
from app.core import agent_flow, audit, case_access
from app.core.config import settings
from app.core.exceptions import TooManyRequests
from app.models.auth_schemas import CurrentUser
from app.models.case_schemas import (
    CreateCaseRequest,
    CreateCaseResponse,
    CaseStatusResponse,
    CaseListItemResponse,
    CaseEventResponse,
)
from app.orchestrator import case_pipeline


def create_case(request: CreateCaseRequest, user: CurrentUser) -> CreateCaseResponse:
    staff = case_access.can_view_all(user)
    # A requester always files as themselves; only staff may file on someone else's behalf.
    requester_id = (request.requester_id or "").strip() if staff else ""
    requester_id = requester_id or user.username

    # A double-click or a re-submit of the same text must not open (and pay AI costs for) a second case.
    raw_request = request.raw_request.strip()
    existing = operations_agent.find_recent_duplicate(requester_id, raw_request, settings.DUPLICATE_REQUEST_MINUTES)
    if existing:
        return CreateCaseResponse(case_id=existing)

    if not staff:
        limit = settings.MAX_REQUESTS_PER_USER_PER_DAY
        if operations_agent.count_recent_cases(requester_id) >= limit:
            raise TooManyRequests(limit)

    case_id = case_pipeline.start_case(requester_id=requester_id, raw_request=raw_request, needed_by=request.needed_by, urgent=request.urgent)
    audit.record(
        "case.create", actor_user_id=user.user_id, actor_username=user.username,
        target_type="case", target_id=case_id,
        detail={"requester_id": requester_id, "on_behalf": requester_id != user.username},
    )
    return CreateCaseResponse(case_id=case_id)


def get_case_status(case_id: str, user: CurrentUser) -> CaseStatusResponse:
    case_access.assert_can_view(user, case_id)
    return CaseStatusResponse(**operations_agent.get_case_status(case_id))


def get_all_cases(user: CurrentUser) -> list[CaseListItemResponse]:
    cases = operations_agent.get_all_cases(case_access.requester_filter(user))
    return [CaseListItemResponse(**c) for c in cases]


def get_case_events(case_id: str, user: CurrentUser) -> list[CaseEventResponse]:
    case_access.assert_can_view(user, case_id)
    events = case_access.visible_events(operations_agent.get_case_events(case_id), user)
    staff = case_access.can_view_all(user)
    return [CaseEventResponse(**event, label=agent_flow.staff_label(event["event_type"]) if staff else None) for event in events]
