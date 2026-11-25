"""Read the text out of email attachments (PDF, Excel, CSV, text) so a supplier's quote or invoice
sent as a file is handled like one typed in the email.

Never raises: anything unreadable (scanned/image-only PDF, password-protected, corrupt, too big,
unsupported type) comes back as None, and the pipeline asks a person to enter it by hand instead.
Limits keep a huge or hostile file from costing time or AI tokens.
"""

import csv
import io
import logging
from pathlib import PurePath

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_SHEETS = 3
MAX_SHEET_ROWS = 200
MAX_CHARS_PER_FILE = 4000
MAX_TOTAL_CHARS = 6000


def extract_text(filename: str, data: bytes) -> str | None:
    """The readable text of one attachment, or None if it can't be read.
    An empty string means it was readable but contained no text (e.g. a blank sheet)."""
    if len(data) > MAX_BYTES:
        return None
    suffix = PurePath(filename or "").suffix.lower()
    try:
        if suffix == ".pdf":
            text = _pdf(data)
        elif suffix == ".xlsx":
            text = _xlsx(data)
        elif suffix in (".csv", ".txt"):
            text = _plain(data)
        else:
            return None
    except Exception:
        logger.warning("could not read attachment %r", filename, exc_info=True)
        return None
    return text[:MAX_CHARS_PER_FILE] if text is not None else None


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
MAX_IMAGE_WIDTH = 1400


def page_images(filename: str, data: bytes, max_pages: int) -> list[bytes]:
    """JPEG pictures of a document that has no text to read: the first pages of a scanned PDF, or a photo of an invoice.
    Never raises; [] when it cannot be done (encrypted, corrupt, too big, not a picture)."""
    if len(data) > MAX_BYTES or max_pages < 1:
        return []
    suffix = PurePath(filename or "").suffix.lower()
    try:
        if suffix == ".pdf":
            return _render_pdf(data, max_pages)
        if suffix in IMAGE_SUFFIXES:
            return [_shrink(data)]
    except Exception:
        logger.warning("could not turn attachment %r into page images", filename, exc_info=True)
    return []


def _jpeg(image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=72)
    return buffer.getvalue()


def _render_pdf(data: bytes, max_pages: int) -> list[bytes]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    pages = []
    for index in range(min(len(pdf), max_pages)):
        page = pdf[index]
        scale = min(2.0, MAX_IMAGE_WIDTH / max(page.get_width(), 1.0))
        pages.append(_jpeg(page.render(scale=scale).to_pil()))
    return pages


def _shrink(data: bytes) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.width > MAX_IMAGE_WIDTH:
        image = image.resize((MAX_IMAGE_WIDTH, round(image.height * MAX_IMAGE_WIDTH / image.width)))
    return _jpeg(image)


def collect_images(attachments: list[dict], max_pages: int) -> list[str]:
    """Base64 page pictures (at most `max_pages` in all) of the attachments that have no readable text."""
    found: list[str] = []
    for attachment in attachments:
        if (attachment.get("text") or "").strip():
            continue
        for image in attachment.get("images") or []:
            if len(found) < max_pages:
                found.append(image)
    return found


def combine(attachments: list[dict]) -> str:
    """One block of text for every readable attachment, labelled by file name, within the total limit."""
    blocks, used = [], 0
    for attachment in attachments:
        text = (attachment.get("text") or "").strip()
        if not text:
            continue
        block = f"[Attachment: {attachment['name']}]\n{text}"[: MAX_TOTAL_CHARS - used]
        blocks.append(block)
        used += len(block)
        if used >= MAX_TOTAL_CHARS:
            break
    return "\n\n".join(blocks)


def unreadable_names(attachments: list[dict]) -> list[str]:
    """File names that were attached but could not be read (so a person should look at them). A document the AI can look at
    as a picture counts as readable."""
    return [a["name"] for a in attachments if not (a.get("text") or "").strip() and not a.get("images")]


def _pdf(data: bytes) -> str | None:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return None
    pages = reader.pages[:MAX_PDF_PAGES]
    return "\n".join((page.extract_text() or "").strip() for page in pages).strip()


def _xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for sheet in workbook.worksheets[:MAX_SHEETS]:
        for row in sheet.iter_rows(max_row=MAX_SHEET_ROWS, values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _plain(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    if text.count(",") > 3:  # looks like a CSV: tidy it into readable rows
        rows = csv.reader(io.StringIO(text))
        return "\n".join(" | ".join(c.strip() for c in row if c.strip()) for row in rows)
    return text.strip()
