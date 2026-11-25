from app.agents import document_agent
from app.core import audit
from app.models.auth_schemas import CurrentUser
from app.models.document_schemas import AttachDocumentRequest, AttachDocumentResponse, DismissDocumentRequest, UnmatchedDocument
from app.orchestrator import case_pipeline


def list_unmatched() -> list[UnmatchedDocument]:
    return [UnmatchedDocument(**d) for d in document_agent.list_open()]


def attach(document_id: str, request: AttachDocumentRequest, user: CurrentUser) -> AttachDocumentResponse:
    outcome = case_pipeline.attach_document(document_id, request.case_id, user.username)
    audit.record("document.attach", actor_user_id=user.user_id, actor_username=user.username, target_type="document", target_id=document_id,
                 detail={"case_id": request.case_id, "result": outcome})
    return AttachDocumentResponse(outcome=outcome)


def dismiss(document_id: str, request: DismissDocumentRequest, user: CurrentUser) -> None:
    case_pipeline.dismiss_document(document_id, user.username, request.note)
    audit.record("document.dismiss", actor_user_id=user.user_id, actor_username=user.username, target_type="document", target_id=document_id,
                 detail={"note": request.note})
