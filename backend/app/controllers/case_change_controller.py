from app.agents import operations_agent
from app.core import access, audit
from app.core.exceptions import CaseNotFound, Forbidden
from app.models.auth_schemas import CurrentUser
from app.models.case_change_schemas import ChangeOptions, ChangeOutcome
from app.orchestrator import case_pipeline


def _may_touch(case_id: str, user: CurrentUser) -> None:
    """The person who asked, or staff who can edit cases. Anyone else gets "not found" so case ids cannot be probed."""
    case = operations_agent.get_case_status(case_id)
    own = (case.get("requester_id") or "").strip().lower() == user.username.strip().lower()
    if not (own or access.has_permission(user.role, "cases:write")):
        raise CaseNotFound(case_id)


def _stores_or_editor(user: CurrentUser) -> bool:
    return access.has_permission(user.role, "stock:write") or access.has_permission(user.role, "cases:write")


def get_options(case_id: str, user: CurrentUser) -> ChangeOptions:
    from_stock = case_pipeline.cancel_options(case_id)["phase"] == "from_stock"
    if not (from_stock and access.has_permission(user.role, "stock:write")):
        _may_touch(case_id, user)
    options = case_pipeline.cancel_options(case_id)
    if options["phase"] == "from_stock" and not _stores_or_editor(user):
        # Same rule as cancel() below: putting goods back on the shelf count is for Stores. The page hides the button instead of offering it and refusing.
        options = {**options, "can_cancel": False, "note": "This was filled from stock. To cancel it, please contact Stores."}
    return ChangeOptions(**options)


def cancel(case_id: str, reason: str | None, user: CurrentUser) -> ChangeOutcome:
    from_stock = case_pipeline.cancel_options(case_id)["phase"] == "from_stock"
    if from_stock and access.has_permission(user.role, "stock:write"):
        pass                                                        # Stores may cancel what was taken from the shelf
    else:
        _may_touch(case_id, user)                                   # (anyone else who may not see the case gets "not found")
        if from_stock and not _stores_or_editor(user):
            # Cancelling puts goods back on the shelf count, and nobody here can tell whether they were already handed over: Stores decides.
            raise Forbidden("This request was filled from stock. Please contact Stores to cancel it, so the goods can be checked and put back.")
    result = case_pipeline.cancel_case(case_id, user.username, reason)
    audit.record("case.cancel", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
                 detail={"reason": reason, "outcome": result["outcome"]})
    return ChangeOutcome(**result)


def change(case_id: str, quantities: dict[str, int], note: str | None, user: CurrentUser) -> ChangeOutcome:
    _may_touch(case_id, user)
    result = case_pipeline.change_case(case_id, user.username, quantities, note)
    audit.record("case.change", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
                 detail={"changes": result.get("changes"), "outcome": result["outcome"]})
    return ChangeOutcome(outcome=result["outcome"])


def resolve_cancel(case_id: str, action: str, note: str | None, user: CurrentUser) -> ChangeOutcome:
    result = case_pipeline.resolve_cancellation(case_id, action, user.username, note)
    audit.record("po.cancel_resolve", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
                 detail={"action": action, "note": note})
    return ChangeOutcome(outcome=result["outcome"])


def resolve_change(case_id: str, action: str, total_amount, note: str | None, user: CurrentUser) -> ChangeOutcome:
    result = case_pipeline.resolve_change(case_id, action, user.username, total_amount, note)
    audit.record("po.change_resolve", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
                 detail={"action": action, "total_amount": total_amount, "note": note})
    return ChangeOutcome(outcome=result["outcome"])
