"""Readable case numbers: REQ-<year>-<running number>, e.g. REQ-2026-0007.

The running number restarts at 1 each year and is handed out by the database in order (see
case_repository.insert_case), so it is unique, never reused and has no gaps. Pure helpers only."""

import re

PREFIX = "REQ"
_PATTERN = re.compile(r"^REQ-(\d{4})-(\d{4,})$", re.IGNORECASE)


def format_case_number(year: int, n: int) -> str:
    """Four digits minimum; a busy year simply grows to five (REQ-2026-10000), never truncates."""
    return f"{PREFIX}-{year}-{n:04d}"


def parse_case_number(text: str) -> tuple[int, int] | None:
    """(year, number) from something a person typed, or None if it is not a case number."""
    match = _PATTERN.match((text or "").strip())
    return (int(match.group(1)), int(match.group(2))) if match else None
