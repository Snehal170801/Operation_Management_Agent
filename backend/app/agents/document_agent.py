"""Documents from a known supplier that name no order we can find. Kept for a person to attach to the right case, so nothing
a supplier sends is ever dropped without a trace."""

import json
import logging
import re

from app.core.exceptions import DocumentAlreadyHandled, DocumentNotFound
from app.repositories import read_file_repository as read_file_repo
from app.repositories import unmatched_document_repository as repo

logger = logging.getLogger(__name__)

_MAX_PAYLOAD_CHARS = 400_000          # a few page pictures; if it would be more, the pictures are left out (the text stays)
_MONEY = re.compile(r"(?:Rs\.?|INR|\u20b9)\s*[\d,]{3,}", re.IGNORECASE)
_WORDS = re.compile(r"\b(invoice|quotation|quote|bill|purchase order|delivery note|credit note|price)\b", re.IGNORECASE)


def looks_like_a_document(message: dict) -> bool:
    """Worth keeping for a person: it has an attachment, an amount, or says what it is. A supplier's newsletter is not."""
    text = f"{message.get('subject') or ''} {message.get('body') or ''}"
    return bool(message.get("attachments")) or bool(_MONEY.search(text)) or bool(_WORDS.search(text))


def _present(row) -> dict:
    payload = json.loads(row.payload or "{}")
    return {
        "document_id": str(row.document_id), "from_email": row.from_email, "vendor_name": row.vendor_name, "subject": row.subject or "",
        "summary": row.summary or "", "file_names": [n for n in (row.file_names or "").split("|") if n], "status": row.status,
        "case_id": str(row.case_id) if row.case_id else None, "handled_by": row.handled_by, "handled_at": row.handled_at,
        "note": row.note, "created_at": row.created_at,
        "body": payload.get("body", ""), "attachments": payload.get("attachments", []),
    }


def record(message: dict, vendor_name: str | None) -> str:
    attachments = message.get("attachments") or []
    payload = {"body": (message.get("body") or "")[:8000], "attachments": attachments}
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > _MAX_PAYLOAD_CHARS:
        payload["attachments"] = [{k: v for k, v in a.items() if k != "images"} for a in attachments]
        text = json.dumps(payload, ensure_ascii=False)[:_MAX_PAYLOAD_CHARS]
    summary = re.sub(r"\s+", " ", (message.get("body") or "").strip())[:280]
    return repo.insert_document(
        message["from_email"], vendor_name, (message.get("subject") or "")[:500], summary,
        "|".join(a.get("name", "") for a in attachments)[:600], text,
    )


def list_open() -> list[dict]:
    return [{k: v for k, v in _present(r).items() if k not in ("body", "attachments")} for r in repo.find_open()]


def get(document_id: str) -> dict:
    row = repo.find_by_id(document_id)
    if row is None:
        raise DocumentNotFound(document_id)
    return _present(row)


def mark_attached(document_id: str, case_id: str, by: str) -> None:
    if not repo.mark_handled(document_id, "attached", by, case_id, None):
        raise DocumentAlreadyHandled(document_id)


def dismiss(document_id: str, by: str, note: str | None) -> None:
    get(document_id)                                   # DocumentNotFound for an unknown id
    if not repo.mark_handled(document_id, "dismissed", by, None, (note or "").strip()[:500] or None):
        raise DocumentAlreadyHandled(document_id)


def list_read_files() -> list[dict]:
    """Every file read so far: {case_id, file_hash, file_name, first_read_at}. Names and dates only, never the content."""
    return [{"case_id": str(r.case_id), "file_hash": r.file_hash.strip(), "file_name": r.file_name, "first_read_at": r.first_read_at} for r in read_file_repo.find_all()]


def known_file_hashes(case_id: str) -> set[str]:
    """Fingerprints of the attachments already read for this case. If the lookup fails the answer is "none known": reading a file
    twice costs a little, refusing to read a new one would lose a supplier's quote."""
    try:
        return read_file_repo.known_hashes(case_id)
    except Exception:
        logger.exception("Could not look up the files already read for case %s", case_id)
        return set()


def remember_files(case_id: str, files: list[tuple[str, str]]) -> None:
    try:
        read_file_repo.remember(case_id, files)
    except Exception:
        logger.exception("Could not remember the files read for case %s", case_id)
