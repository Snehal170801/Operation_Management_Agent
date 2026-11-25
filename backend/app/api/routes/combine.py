from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.core import audit
from app.models.auth_schemas import CurrentUser
from app.models.combine_schemas import CombineRequest, CombineResult, CombineSuggestion
from app.orchestrator import case_pipeline

# Staff who work with suppliers (vendors:write). A requester never sees another person's request.
router = APIRouter(prefix="/cases/{case_id}/combine", tags=["combine"])


@router.get("", response_model=list[CombineSuggestion], dependencies=[Depends(require_permission("vendors:read"))])
def suggestions(case_id: str):
    """Requests for the same item that could be combined with this one."""
    return [CombineSuggestion(keep_case_id=s["older"], keep_number=s["older_number"], fold_case_id=s["newer"], fold_number=s["newer_number"],
                              matches=s["matches"], since=s["since"]) for s in case_pipeline.combine_suggestions(case_id)]


@router.post("", response_model=CombineResult)
def combine(case_id: str, request: CombineRequest, user: CurrentUser = Depends(require_permission("vendors:write"))):
    """Combine this request with the other: the older carries on with both quantities, the newer is closed as combined."""
    result = case_pipeline.combine_cases(case_id, request.other_case_id, user.username)
    audit.record("case.combine", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=result["primary_case_id"],
                 detail={"closed_case_id": result["closed_case_id"]})
    return CombineResult(primary_case_id=result["primary_case_id"], closed_case_id=result["closed_case_id"])


@router.post("/dismiss", status_code=204)
def dismiss(case_id: str, request: CombineRequest, user: CurrentUser = Depends(require_permission("vendors:write"))):
    """Keep these two requests separate: the suggestion is not made again."""
    case_pipeline.dismiss_combine(case_id, request.other_case_id, user.username)
    audit.record("case.combine_dismiss", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
                 detail={"other_case_id": request.other_case_id})
