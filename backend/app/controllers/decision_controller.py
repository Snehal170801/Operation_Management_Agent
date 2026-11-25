"""Deciding an approval from an email link. The page can be opened by anyone holding the link, so everything is checked again here:
the link, the approval, and that the person it was made for may still decide it."""

from datetime import datetime, timezone

from app.agents import approval_agent, approval_link_agent, operations_agent
from app.controllers import approval_controller
from app.core import access, audit, email_approval, tax
from app.core.config import settings
from app.core.exceptions import ApprovalAlreadyDecided, LinkProblem, RuleViolation
from app.core.permissions import ADMIN_ROLE
from app.core.separation import check_not_own_request
from app.models.decision_schemas import DecisionInfo, DecisionOption, DecisionPriceChange, DecisionResult
from app.orchestrator import case_pipeline
from app.repositories import user_repository


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _open_link(token: str, record_refusal: bool = False):
    """(link, approval, person) for a link that can be used right now, or LinkProblem. When `record_refusal` is set (a decision was
    attempted, not just a page opened) a link made for someone who can no longer approve leaves a note on the case."""
    link = approval_link_agent.find(token)
    problem = email_approval.link_problem(link, _now())
    if problem:
        raise LinkProblem(problem)
    try:
        approval = approval_agent.get_approval(link["approval_id"])
    except Exception:
        raise LinkProblem("invalid") from None
    if approval["status"] != "pending":
        raise LinkProblem("decided")
    person = user_repository.find_user_by_id(link["user_id"])
    if person is None or not person.is_active or not access.has_permission(person.role, "approvals:write"):
        if record_refusal:
            try:
                operations_agent.publish_event(approval["case_id"], "approval.link_refused", agent_name="Approval Agent",
                                               payload={"approval_id": approval["approval_id"], "reason": "The link was made for someone who can no longer approve orders."})
            except Exception:
                pass                                            # the refusal itself must not depend on the note
        raise LinkProblem("person")
    return link, approval, person


def _within_limit(review) -> bool:
    chosen = next((o for o in review.options if o.vendor_id == review.selected_vendor_id), None)
    amount = review.price_change.new_total if review.kind == "price_change" and review.price_change else (chosen.price if chosen else None)
    amount = tax.cost(amount, settings.TAX_RATE_PCT, settings.TAX_INCLUDED_IN_QUOTES)           # the limit is about what it really costs: with tax
    return email_approval.offer_link(settings.EMAIL_APPROVE_ENABLED, amount, settings.EMAIL_APPROVE_MAX_AMOUNT, review.kind)


def get_info(token: str) -> DecisionInfo:
    """Show the order. Changes nothing, so opening the link (or an email scanner doing so) is harmless."""
    link, approval, person = _open_link(token)
    review = approval_controller.get_review(approval["approval_id"])
    if not _within_limit(review):
        raise LinkProblem("revoked")                    # the amount grew past the limit, or the feature was switched off since
    case = operations_agent.get_case_status(approval["case_id"])
    blocked = None
    try:
        check_not_own_request(person.username, case.get("requester_id"), person.role == ADMIN_ROLE)
    except RuleViolation as exc:
        blocked = str(exc)
    chosen = next((o for o in review.options if o.vendor_id == review.selected_vendor_id), None)
    return DecisionInfo(
        kind=review.kind, case_number=review.case_number, recipient=person.display_name or person.username,
        request_text=review.request_text, items=[i.model_dump() for i in review.items], reasons=review.reasons,
        urgent=review.urgent, needed_by=review.needed_by,
        chosen=DecisionOption(vendor_name=chosen.vendor_name, price=chosen.price, lead_time_days=chosen.lead_time_days, terms=chosen.terms, tags=chosen.tags) if chosen else None,
        other_offers=max(0, len(review.options) - 1),
        price_change=DecisionPriceChange(**review.price_change.model_dump(exclude={"reply_text"})) if review.price_change else None,
        expires_at=link["expires_at"], can_decide=blocked is None, blocked=blocked,
    )


def decide(token: str, action: str, note: str | None, ip: str | None) -> DecisionResult:
    link, approval, person = _open_link(token, record_refusal=True)
    review = approval_controller.get_review(approval["approval_id"])
    if not _within_limit(review):
        raise LinkProblem("revoked")
    case = operations_agent.get_case_status(approval["case_id"])
    override = check_not_own_request(person.username, case.get("requester_id"), person.role == ADMIN_ROLE)   # raises for a person's own request
    approve = action == email_approval.APPROVE

    if not approval_link_agent.use(link["link_id"], action, ip):          # of two taps at once, only one gets through
        raise LinkProblem("used")
    try:
        case_pipeline.decide_approval(approval["approval_id"], approve, person.username, (note or "").strip() or None)
    except ApprovalAlreadyDecided:
        raise LinkProblem("decided") from None
    approval_link_agent.revoke_all(approval["approval_id"])
    audit.record(
        "approval.approve" if approve else "approval.reject", actor_user_id=str(person.user_id), actor_username=person.username,
        target_type="approval", target_id=approval["approval_id"], ip=ip,
        detail={"case_id": approval["case_id"], "via": "email_link", "note": note, **({"override": override} if override else {})},
    )
    word = "approved" if approve else "refused"
    return DecisionResult(outcome=word, case_number=review.case_number,
                          message=f"Done. {review.case_number or 'The order'} is {word}." + (" The order is being sent to the supplier." if approve and review.kind == "vendor_selection" else ""))
