"""Has this attachment been read before? A fingerprint of what we would send to the AI (the text, or the page pictures), so the same file
is never paid for twice: a supplier re-sending a PDF, or two copies of one mail. Pure functions, no database."""

import hashlib


def fingerprint(attachment: dict) -> str | None:
    """sha256 of the attachment's content, or None when there is nothing readable in it (nothing would reach the AI anyway).
    A hash supplied with the attachment (`sha256`, of the raw file) is used as is. The file NAME is not part of it: renaming a file
    does not make it new."""
    if attachment.get("sha256"):
        return str(attachment["sha256"]).lower()
    text = (attachment.get("text") or "").strip()
    images = attachment.get("images") or []
    if not text and not images:
        return None
    digest = hashlib.sha256()
    digest.update(text.encode("utf-8", errors="replace"))
    for image in images:
        digest.update(b"\x00" + str(image).encode("utf-8", errors="replace"))
    return digest.hexdigest()


def split(attachments: list[dict], known: set[str]) -> tuple[list[dict], list[dict], list[tuple[str, str]]]:
    """(fresh attachments to read, repeated ones to skip, [(hash, name)] of the fresh ones to remember once they have been handled).
    An attachment with nothing readable stays "fresh" (the pipeline already reports unreadable files). A second copy inside the same email
    is a repeat too."""
    fresh, repeated, to_remember, seen = [], [], [], set(known)
    for attachment in attachments:
        h = fingerprint(attachment)
        if h is None:
            fresh.append(attachment)
        elif h in seen:
            repeated.append(attachment)
        else:
            seen.add(h)
            fresh.append(attachment)
            to_remember.append((h, attachment.get("name") or ""))
    return fresh, repeated, to_remember
