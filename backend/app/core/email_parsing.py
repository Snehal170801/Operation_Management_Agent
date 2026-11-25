"""Pure helpers for matching and cleaning vendor reply emails."""

import re

REF_PREFIX = "[OA-"
_REF_RE = re.compile(r"\[OA-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\]")
_REPLY_HEADER_RE = re.compile(r"^\s*(On .+ wrote:|-{2,} ?Original Message ?-{2,}|From: .+)\s*$", re.IGNORECASE)
_MAX_BODY_CHARS = 5000


def make_subject(case_id: str, title: str = "Request for quotation") -> str:
    return f"{REF_PREFIX}{case_id}] {title}"


def parse_case_ref(subject: str) -> str | None:
    match = _REF_RE.search(subject or "")
    return match.group(1).lower() if match else None


def clean_reply_body(body: str) -> str:
    """Keep only what the vendor newly wrote: drop quoted lines and everything after
    the 'On ... wrote:' / 'Original Message' marker."""
    kept = []
    for line in (body or "").splitlines():
        if _REPLY_HEADER_RE.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()[:_MAX_BODY_CHARS]
