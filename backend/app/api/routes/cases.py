from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.controllers import case_controller
from app.models.auth_schemas import CurrentUser
from app.models.case_schemas import (
    CreateCaseRequest,
    CreateCaseResponse,
    CaseStatusResponse,
    CaseListItemResponse,
    CaseEventResponse,
)

# Each route names its own permission: requesters hold only cases:read (their own cases, filtered
# in the controller) and cases:create; staff hold cases:read_all as well.
router = APIRouter(prefix="/cases", tags=["cases"])

_can_read = require_permission("cases:read")
_can_create = require_permission("cases:create")


@router.post("", response_model=CreateCaseResponse)
def create_case(request: CreateCaseRequest, user: CurrentUser = Depends(_can_create)):
    return case_controller.create_case(request, user)


@router.get("", response_model=list[CaseListItemResponse])
def get_all_cases(user: CurrentUser = Depends(_can_read)):
    return case_controller.get_all_cases(user)


@router.get("/{case_id}", response_model=CaseStatusResponse)
def get_case_status(case_id: str, user: CurrentUser = Depends(_can_read)):
    return case_controller.get_case_status(case_id, user)


@router.get("/{case_id}/events", response_model=list[CaseEventResponse])
def get_case_events(case_id: str, user: CurrentUser = Depends(_can_read)):
    return case_controller.get_case_events(case_id, user)
