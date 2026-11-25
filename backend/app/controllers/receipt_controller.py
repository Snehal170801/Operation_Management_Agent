from app.agents import delivery_agent, notification_agent, operations_agent
from app.core import audit
from app.core.exceptions import CaseNotFound, InvalidInput
from app.models.auth_schemas import CurrentUser
from app.models.delivery_schemas import ReceiptResponse


def _own_case(case_id: str, user: CurrentUser) -> dict:
    """The requester's own case. Anyone else gets "not found", so case ids can't be probed."""
    case = operations_agent.get_case_status(case_id)
    if (case.get("requester_id") or "").strip().lower() != user.username.strip().lower():
        raise CaseNotFound(case_id)
    return case


def get_receipt(case_id: str, user: CurrentUser) -> ReceiptResponse:
    _own_case(case_id, user)
    return ReceiptResponse(**delivery_agent.get_receipt(case_id))


def answer(case_id: str, received: bool, note: str | None, user: CurrentUser) -> ReceiptResponse:
    case = _own_case(case_id, user)
    current = delivery_agent.get_receipt(case_id)
    if current["state"] == "not_delivered":
        raise InvalidInput("Receiving has not marked these goods as received yet, so there is nothing to confirm.")
    delivery_agent.record_receipt(case_id, user.username, received, note)
    audit.record(
        "delivery.requester_confirmed" if received else "delivery.requester_disputed",
        actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
    )
    if not received:
        reason = f"{user.username} says the goods for {case.get('case_number') or 'a request'} have not reached them."
        if note and note.strip():
            reason += f" They wrote: {note.strip()[:300]}"
        notification_agent.notify_case_stalled(case_id, reason, team="delivery")
    return ReceiptResponse(**delivery_agent.get_receipt(case_id))


def dispute_handled(case_id: str, note: str | None, user: CurrentUser) -> None:
    operations_agent.get_case_status(case_id)  # CaseNotFound for an unknown case
    delivery_agent.record_dispute_handled(case_id, user.username, note)
    audit.record(
        "delivery.dispute_handled", actor_user_id=user.user_id, actor_username=user.username,
        target_type="case", target_id=case_id, detail={"note": note},
    )
