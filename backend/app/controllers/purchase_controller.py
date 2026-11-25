from app.agents import purchase_agent
from app.core import case_access
from app.models.auth_schemas import CurrentUser
from app.models.purchase_schemas import PurchaseRequestResponse


def get_purchase_request(case_id: str, user: CurrentUser) -> PurchaseRequestResponse:
    case_access.assert_can_view(user, case_id)
    result = purchase_agent.get_purchase_request(case_id)
    return PurchaseRequestResponse(**result)
