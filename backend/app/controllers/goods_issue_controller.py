from app.agents import delivery_agent
from app.core import audit
from app.models.auth_schemas import CurrentUser
from app.models.goods_issue_schemas import GoodsIssue
from app.orchestrator import case_pipeline


def list_issues(case_id: str) -> list[GoodsIssue]:
    return [GoodsIssue(**i) for i in delivery_agent.get_issues(case_id)]


def report(case_id: str, kind: str, items: dict[str, int] | None, description: str | None, user: CurrentUser) -> GoodsIssue:
    issue = case_pipeline.report_goods_issue(case_id, kind, items, description, user.username)
    audit.record("goods.issue_report", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
                 detail={"issue_id": issue["issue_id"], "kind": kind, "items": issue["items"]})
    return GoodsIssue(**issue)


def _on_this_case(case_id: str, issue_id: str) -> None:
    if delivery_agent.get_issue(issue_id)["case_id"].lower() != case_id.lower():
        from app.core.exceptions import InvalidInput
        raise InvalidInput("That problem is not on this request.")


def return_goods(case_id: str, issue_id: str, ref: str | None, user: CurrentUser) -> GoodsIssue:
    _on_this_case(case_id, issue_id)
    issue = case_pipeline.return_goods(issue_id, ref, user.username)
    audit.record("goods.return", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id, detail={"issue_id": issue_id, "ref": ref})
    return GoodsIssue(**issue)


def expect_replacement(case_id: str, issue_id: str, user: CurrentUser) -> GoodsIssue:
    _on_this_case(case_id, issue_id)
    issue = case_pipeline.expect_goods_replacement(issue_id, user.username)
    audit.record("goods.replacement_expected", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id, detail={"issue_id": issue_id})
    return GoodsIssue(**issue)


def receive_replacement(case_id: str, issue_id: str, note: str | None, user: CurrentUser) -> GoodsIssue:
    _on_this_case(case_id, issue_id)
    issue = case_pipeline.receive_goods_replacement(issue_id, note, user.username)
    audit.record("goods.replacement_received", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id, detail={"issue_id": issue_id, "note": note})
    return GoodsIssue(**issue)


def resolve(case_id: str, issue_id: str, resolution: str, credit_amount, note: str | None, user: CurrentUser, credit_note_number: str | None = None) -> GoodsIssue:
    _on_this_case(case_id, issue_id)
    issue = case_pipeline.resolve_goods_issue(issue_id, resolution, credit_amount, note, user.username, credit_note_number)
    audit.record("goods.issue_resolve", actor_user_id=user.user_id, actor_username=user.username, target_type="case", target_id=case_id,
                 detail={"issue_id": issue_id, "resolution": resolution, "credit_amount": credit_amount, "credit_note_number": credit_note_number, "note": note})
    return GoodsIssue(**issue)
