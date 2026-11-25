from datetime import datetime, timezone

from app.agents import approval_agent, delivery_agent, invoice_agent, operations_agent, purchase_agent, purchase_order_agent, vendor_agent
from app.core import case_access
from app.controllers.invoice_suggestions import attach_suggestions
from app.core.agent_info import AGENT_KEYS, as_of, build_agent_info
from app.core.exceptions import PurchaseOrderNotFound, PurchaseRequestNotFound, RuleViolation, VendorSelectionNotFound
from app.core.agent_flow import apply_expected_delivery, build_board, build_board_feed, build_replay, build_flow, headline_for
from app.models.agent_flow_schemas import AgentBoard, AgentInfo, AgentReplay, AgentFlowCase, AgentFlowState, RequestDetails, RequestItem
from app.models.auth_schemas import CurrentUser
from app.repositories import dashboard_repository

MAX_CASES = 30
MAX_BOARD_CASES = 60  # the board shows the most recently active open cases


def list_cases(user: CurrentUser) -> list[AgentFlowCase]:
    """The cases the person can look at (a requester: their own; staff: all), the ones still being worked on
    first, newest activity first."""
    staff = case_access.can_view_all(user)
    cases = operations_agent.get_all_cases(case_access.requester_filter(user))
    cases.sort(key=lambda c: c["updated_at"], reverse=True)
    cases.sort(key=lambda c: c["status"] != "open")          # stable: open cases come first
    return [
        AgentFlowCase(
            case_id=c["case_id"], case_number=c.get("case_number"), items_summary=c["items_summary"], stage=c["stage"], status=c["status"],
            active=c["status"] == "open", headline=headline_for(c["stage"], c["status"], staff),
            updated_at=c["updated_at"], requester=c["requester_id"] if staff else None,
        )
        for c in cases[:MAX_CASES]
    ]


def _request_details(case: dict, staff: bool) -> RequestDetails | None:
    """The request in full, for the person allowed to see this case (a requester only ever gets their own)."""
    try:
        pr = purchase_agent.get_purchase_request(case["case_id"])
    except PurchaseRequestNotFound:
        return None
    return RequestDetails(
        raw_text=pr["raw_request"], cost_center=pr.get("cost_center"), submitted_at=pr.get("created_at") or case.get("created_at"),
        items=[RequestItem(**i) for i in pr["items"]], requested_by=case.get("requester_id") if staff else None,
    )


def _expected_delivery(case_id: str):
    """The date the goods are due, once an order exists."""
    try:
        due = delivery_agent.get_delivery(case_id)["expected_delivery_date"]
    except PurchaseOrderNotFound:
        return None
    return due.date() if hasattr(due, "date") else due


def _missing(fetch, *args):
    """Whatever an agent has not produced yet is simply absent."""
    try:
        return fetch(*args)
    except (PurchaseRequestNotFound, PurchaseOrderNotFound, VendorSelectionNotFound):
        return None


# What each agent's detail needs, so a click only reads what it shows.
_NEEDS = {
    "purchase": {"request"}, "procurement": set(), "operations": set(), "notification": set(),
    "vendor": {"rfqs", "quotes", "selection", "vendors"}, "approval": {"approvals", "quotes", "selection", "vendors"},
    "po": {"po"}, "delivery": {"delivery"}, "invoice": {"invoices", "po", "delivery"},
}


def get_agent_info(case_id: str, key: str, user: CurrentUser, at=None) -> AgentInfo:
    """Everything one agent did on this case, in full for staff and without money or supplier names for a requester."""
    case_access.assert_can_view(user, case_id)       # 404 for someone else's case, never 403
    if key not in AGENT_KEYS:
        raise RuleViolation(f"There is no agent called '{key}'.")
    need = _NEEDS[key]
    data: dict = {"case": operations_agent.get_case_status(case_id), "events": operations_agent.get_case_events(case_id)}
    if "request" in need:
        data["request"] = _missing(purchase_agent.get_purchase_request, case_id)
    if "rfqs" in need:
        data["rfqs"] = vendor_agent.get_rfqs(case_id)
    if "quotes" in need:
        data["quotes"] = vendor_agent.get_quotes(case_id)
        data["earlier_quotes"] = vendor_agent.get_earlier_quotes(case_id)
    if "selection" in need:
        data["selection"] = _missing(vendor_agent.get_vendor_selection, case_id)
    if "vendors" in need:
        data["vendors"] = {v["vendor_id"]: v for v in vendor_agent.get_all_vendors()}
    if "approvals" in need:
        data["approvals"] = sorted(approval_agent.get_approvals(case_id=case_id), key=lambda a: a["created_at"])
    if "po" in need:
        data["po"] = purchase_order_agent.find_purchase_order(case_id)
    if "delivery" in need:
        data["delivery"] = _missing(delivery_agent.get_delivery, case_id)
    if "invoices" in need:
        data["invoices"] = attach_suggestions(invoice_agent.get_invoices_with_extraction(case_id))
    if at is not None:  # a replay asks for the account as it was at that moment
        data = as_of(data, at)
    return AgentInfo(**build_agent_info(key, data, case_access.can_view_all(user)))


def get_flow(case_id: str, user: CurrentUser) -> AgentFlowState:
    case_access.assert_can_view(user, case_id)       # 404 for someone else's case, never 403
    case = operations_agent.get_case_status(case_id)
    # The raw events (including the step signals) are only an input here. What leaves is the derived
    # state, worded for the audience: a requester never receives payloads, errors or supplier details.
    events = operations_agent.get_case_events(case_id)
    audience = "staff" if case_access.can_view_all(user) else "requester"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    flow = apply_expected_delivery(build_flow(case, events, audience, now), _expected_delivery(case_id), now.date())
    return AgentFlowState(**flow, case_number=case.get("case_number"),
                          request=_request_details(case, audience == "staff"))


def get_board() -> AgentBoard:
    """Staff only (the route guards it): every agent's workload across the open cases."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    open_cases = [c for c in operations_agent.get_all_cases(None) if c["status"] == "open"]
    open_cases.sort(key=lambda c: c["updated_at"], reverse=True)
    entries = []
    for case in open_cases[:MAX_BOARD_CASES]:
        events = operations_agent.get_case_events(case["case_id"])
        entries.append((case, build_flow(case, events, "staff", now)))
    feed_events = [
        {"event_id": r.event_id, "event_type": r.event_type, "created_at": r.created_at, "case_id": str(r.case_id),
         "case_number": r.case_number, "payload": operations_agent._parse_payload(r.payload)}
        for r in dashboard_repository.recent_agent_events()
    ]
    return AgentBoard(**build_board(entries, now, build_board_feed(feed_events)))


def get_replay(case_id: str, user: CurrentUser) -> AgentReplay:
    case_access.assert_can_view(user, case_id)       # same privacy as the live page
    case = operations_agent.get_case_status(case_id)
    audience = "staff" if case_access.can_view_all(user) else "requester"
    return AgentReplay(**build_replay(case, operations_agent.get_case_events(case_id), audience), case_number=case.get("case_number"),
                       expected_delivery=_expected_delivery(case_id),
                       request=_request_details(case, audience == "staff"))
