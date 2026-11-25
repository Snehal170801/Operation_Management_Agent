import json
import uuid
from datetime import datetime, timezone

from app.agents import operations_agent, vendor_agent
from app.core import quotes as quote_rules
from app.core import urgency
from app.core.approval_policy import human_review_reasons
from app.core.exceptions import ApprovalAlreadyDecided, ApprovalNotFound
from app.repositories import approval_repository, purchase_order_repository

VENDOR_SELECTION = "vendor_selection"
PRICE_CHANGE = "price_change"


def review_vendor_selection(case_id: str, needed_by=None) -> dict:
    """Auto-approve a routine vendor selection; otherwise park it for a human."""
    selection = vendor_agent.get_vendor_selection(case_id)
    quotes = vendor_agent.get_quotes(case_id)
    vendor = next(
        (v for v in vendor_agent.get_all_vendors() if v["vendor_id"] == selection["vendor_id"]),
        None,
    )
    selected_quote = next((q for q in quote_rules.latest_per_vendor(quotes)
                           if q["vendor_id"] == selection["vendor_id"] and q["price"] is not None), None)

    # Orders raised automatically since midnight UTC count against the daily limit.
    midnight = datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    reasons = human_review_reasons(
        selected_quote, vendor["reliability_score"] if vendor else None, quote_rules.vendor_count(quotes),
        spent_today=purchase_order_repository.sum_auto_approved_since(midnight),
        restock=any(e["event_type"] == "restock.requested" for e in operations_agent.get_case_events(case_id)),
    )

    if needed_by and selected_quote and urgency.meets(selected_quote["lead_time_days"], needed_by, datetime.now(timezone.utc).date()) is False:
        reasons.append(f"The supplier's delivery time ({selected_quote['lead_time_days']} days) misses the date it is needed by ({needed_by:%d %b %Y}).")

    approval_repository.supersede_pending(case_id, VENDOR_SELECTION)
    approval_id = str(uuid.uuid4())

    if not reasons:
        approval_repository.insert_approval(
            approval_id, case_id, VENDOR_SELECTION, "auto_approved", [], decided_by="policy",
        )
        operations_agent.publish_event(
            case_id, "approval.auto_approved", agent_name="Approval Agent",
            payload={"approval_id": approval_id},
        )
        operations_agent.set_stage(case_id, "approved")
    else:
        approval_repository.insert_approval(
            approval_id, case_id, VENDOR_SELECTION, "pending", reasons,
        )
        operations_agent.publish_event(
            case_id, "approval.requested", agent_name="Approval Agent",
            payload={"approval_id": approval_id, "reasons": reasons},
        )
        operations_agent.set_stage(case_id, "awaiting_approval")

    return get_approval(approval_id)


def decide(approval_id: str, approve: bool, decided_by: str, note: str | None, re_sourcing: bool = False) -> dict:
    """`re_sourcing` (rejecting only): the offers are turned down but the request is not ended; the caller asks for new quotes."""
    approval = get_approval(approval_id)  # raises ApprovalNotFound
    status = "approved" if approve else "rejected"

    if not approval_repository.decide_pending(approval_id, status, decided_by, note):
        raise ApprovalAlreadyDecided(approval_id)

    case_id = approval["case_id"]
    operations_agent.publish_event(
        case_id, f"approval.{status}", agent_name="Approval Agent",
        payload={"approval_id": approval_id, "decided_by": decided_by, "note": note, "kind": approval.get("approval_type"),
                 **({"re_sourcing": True} if re_sourcing and not approve else {})},
    )
    if approval.get("approval_type") == PRICE_CHANGE:
        return get_approval(approval_id)                    # the case itself carries on exactly as it was
    if approve:
        operations_agent.set_stage(case_id, "approved")
    elif re_sourcing:
        pass  # the case stays open; the pipeline sends it back out for quotes
    else:
        operations_agent.close_case(
            case_id, stage="rejected",
            reason=note or f"Vendor selection rejected by {decided_by}.",
        )

    return get_approval(approval_id)


def get_approval(approval_id: str) -> dict:
    row = approval_repository.find_approval_by_id(approval_id)
    if row is None:
        raise ApprovalNotFound(approval_id)
    return _row_to_dict(row)


def get_approvals(status: str | None = None, case_id: str | None = None) -> list[dict]:
    return [_row_to_dict(r) for r in approval_repository.find_approvals(status, case_id)]


def get_approvals_needing_reminder(cutoff, max_reminders: int) -> list[dict]:
    return [_row_to_dict(r) for r in approval_repository.find_pending_due_for_reminder(cutoff, max_reminders)]


def mark_reminded(approval_id: str) -> None:
    approval_repository.mark_reminded(approval_id)


def _row_to_dict(row) -> dict:
    return {
        "approval_id": str(row.approval_id),
        "case_id": str(row.case_id),
        "case_number": getattr(row, "case_number", None),
        "approval_type": row.approval_type,
        "status": row.status,
        "reasons": json.loads(row.reasons) if row.reasons else [],
        "decided_by": row.decided_by,
        "decision_note": row.decision_note,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
        "last_reminded_at": getattr(row, "last_reminded_at", None),
    }


def withdraw_pending(case_id: str) -> None:
    """The request was cancelled or changed, so a decision still waiting is no longer needed."""
    approval_repository.supersede_pending(case_id, VENDOR_SELECTION)


def request_price_change(case_id: str, reason: str) -> dict:
    """A supplier asks for a higher price on an order already placed: an approver must decide. Only one such question is open
    at a time (a newer ask replaces an older one)."""
    approval_repository.supersede_pending(case_id, PRICE_CHANGE)
    approval_id = str(uuid.uuid4())
    approval_repository.insert_approval(approval_id, case_id, PRICE_CHANGE, "pending", [reason])
    operations_agent.publish_event(
        case_id, "approval.requested", agent_name="Approval Agent",
        payload={"approval_id": approval_id, "reasons": [reason], "kind": PRICE_CHANGE},
    )
    return get_approval(approval_id)
