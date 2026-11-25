from app.agents import delivery_agent, operations_agent, purchase_order_agent
from app.core import audit
from app.models.auth_schemas import CurrentUser
from app.models.delivery_schemas import ConfirmDeliveryRequest, DeliveryResponse
from app.orchestrator import case_pipeline


def get_delivery(case_id: str) -> DeliveryResponse | None:
    """None while there is no order to deliver (an ordinary answer, not an error); a case that does not exist is still 404."""
    if purchase_order_agent.find_purchase_order(case_id) is None:
        operations_agent.get_case_status(case_id)
        return None
    return DeliveryResponse(**delivery_agent.get_delivery(case_id))


def confirm_delivery(case_id: str, request: ConfirmDeliveryRequest, user: CurrentUser) -> DeliveryResponse:
    result = case_pipeline.confirm_delivery(case_id, user.username, request.note, request.items)
    audit.record(
        "delivery.confirm", actor_user_id=user.user_id, actor_username=user.username,
        target_type="case", target_id=case_id, detail={"note": request.note, **({"items": request.items} if request.items else {})},
    )
    return DeliveryResponse(**result)


def short_close(case_id: str, note: str | None, user: CurrentUser) -> DeliveryResponse:
    """Accept that the supplier will not send the rest of the order."""
    result = case_pipeline.short_close_delivery(case_id, user.username, note)
    audit.record(
        "delivery.short_close", actor_user_id=user.user_id, actor_username=user.username,
        target_type="case", target_id=case_id, detail={"note": note},
    )
    return DeliveryResponse(**result)
