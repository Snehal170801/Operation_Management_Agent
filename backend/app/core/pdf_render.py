"""Draws the two documents as PDF with fpdf2 and the built-in fonts (no font files to ship). Input is what `core/documents` builds.

The approval summary is guaranteed to be ONE page: it is drawn at 9 pt and, if that overflows, again at 8 pt and 7.5 pt; `render` raises if
even the smallest does not fit (the content builders already cap every text, so that cannot happen with real data)."""

from fpdf import FPDF

from app.core.documents import safe_text

RED = (197, 53, 54)
INK = (31, 34, 38)
MUTED = (110, 116, 124)
PINK = (251, 234, 234)
LINE = (217, 217, 217)
MARGIN = 14


class TooLong(Exception):
    pass


class _Pdf(FPDF):
    def __init__(self, title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(False)
        self.set_title(safe_text(title))
        self.set_creator("Operation Agents")
        self.add_page()

    @property
    def width(self) -> float:
        return self.w - 2 * MARGIN

    def room(self, needed: float) -> bool:
        return self.get_y() + needed <= self.h - MARGIN - 8

    def text_line(self, text: str, size: float, style: str = "", color=INK, h: float | None = None, align: str = "L", w: float = 0):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.cell(w or self.width, h or size * 0.5, safe_text(text), new_x="LMARGIN", new_y="NEXT", align=align)

    def paragraph(self, text: str, size: float, style: str = "", color=INK, h: float | None = None, w: float = 0):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.multi_cell(w or self.width, h or size * 0.45, safe_text(text), new_x="LMARGIN", new_y="NEXT")

    def rule(self, color=LINE, gap: float = 1.5):
        self.ln(gap)
        self.set_draw_color(*color)
        self.line(MARGIN, self.get_y(), self.w - MARGIN, self.get_y())
        self.ln(gap)

    def section(self, text: str, size: float):
        self.ln(size * 0.25)
        self.text_line(text.upper(), size - 1, "B", RED, h=size * 0.55)

    def header(self_):  # noqa: N805 (fpdf calls this on every page)
        return None


def _letterhead(pdf: _Pdf, doc: dict, size: float, number: str | None) -> None:
    pdf.set_fill_color(*RED)
    pdf.rect(0, 0, pdf.w, 3.2, style="F")
    pdf.set_y(MARGIN - 4)
    pdf.set_font("Helvetica", "B", size + 6)
    pdf.set_text_color(*INK)
    pdf.cell(pdf.width * 0.6, size, safe_text(doc["company"]["name"]), new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "B", size + 4)
    pdf.set_text_color(*RED)
    pdf.cell(pdf.width * 0.4, size, safe_text(doc["title"]), new_x="LMARGIN", new_y="NEXT", align="R")
    for line in doc["company"].get("address") or []:
        pdf.text_line(line, size - 1, "", MUTED, h=size * 0.45)
    if number:
        pdf.text_line(number, size + 1, "B", INK, h=size * 0.55, align="R")
    pdf.rule(RED, 1.2)


def _pair(pdf: _Pdf, label: str, value: str, size: float, label_w: float = 34) -> None:
    pdf.set_font("Helvetica", "B", size)
    pdf.set_text_color(*MUTED)
    pdf.cell(label_w, size * 0.5, safe_text(label), new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "", size)
    pdf.set_text_color(*INK)
    pdf.multi_cell(pdf.width - label_w, size * 0.5, safe_text(value) or "-", new_x="LMARGIN", new_y="NEXT")


def render_purchase_order(doc: dict) -> bytes:
    pdf = _Pdf(f"Purchase order {doc['number']}")
    size = 10
    _letterhead(pdf, doc, size, doc["number"])
    _pair(pdf, "Date", doc["issued"], size)
    if doc.get("case_number"):
        _pair(pdf, "Request", doc["case_number"], size)
    if doc.get("requested_by"):
        _pair(pdf, "Requested by", doc["requested_by"], size)
    _pair(pdf, "Status", doc["status"].capitalize(), size)
    pdf.section("Supplier", size)
    _pair(pdf, "Name", doc["vendor"]["name"], size)
    if doc["vendor"]["email"]:
        _pair(pdf, "E-mail", doc["vendor"]["email"], size)

    pdf.section("Items", size)
    widths = [14, pdf.width - 14 - 28, 28]
    pdf.set_fill_color(*PINK)
    pdf.set_draw_color(*LINE)
    pdf.set_font("Helvetica", "B", size)
    pdf.set_text_color(*INK)
    for text, w, align in (("No.", widths[0], "C"), ("Description", widths[1], "L"), ("Quantity", widths[2], "R")):
        pdf.cell(w, 8, text, border=1, align=align, fill=True, new_x="RIGHT", new_y="TOP")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", size)
    for line in doc["items"]:
        if not pdf.room(9):
            pdf.add_page()
        pdf.cell(widths[0], 8, str(line["no"]), border=1, align="C", new_x="RIGHT", new_y="TOP")
        pdf.cell(widths[1], 8, safe_text(line["description"])[:90], border=1, new_x="RIGHT", new_y="TOP")
        pdf.cell(widths[2], 8, str(line["quantity"]), border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    if doc.get("tax"):
        _pair(pdf, "Subtotal", doc["tax"]["subtotal"], size)
        _pair(pdf, f"Tax ({doc['tax']['rate']})", doc["tax"]["amount"], size)
        _pair(pdf, "Total with tax", doc["tax"]["total"], size + 1)
    else:
        _pair(pdf, "Total amount", doc["total"], size + 1)
    _pair(pdf, "Delivery by", doc["delivery_by"] + (f"  ({doc['lead_time']} from order)" if doc.get("lead_time") else ""), size)
    pdf.section("Terms", size)
    pdf.paragraph(doc["terms"], size)
    pdf.rule()
    pdf.paragraph(doc["footer"], size - 1, "I", MUTED)
    return bytes(pdf.output())


def _draw_summary(doc: dict, size: float) -> _Pdf:
    pdf = _Pdf(f"Approval summary {doc.get('case_number') or ''}")
    _letterhead(pdf, doc, size, doc.get("case_number"))
    meta = [("Requested by", doc["requested_by"])]
    if doc.get("needed_by"):
        meta.append(("Needed by", doc["needed_by"] + ("  (URGENT)" if doc["urgent"] else "")))
    elif doc["urgent"]:
        meta.append(("Priority", "URGENT"))
    if doc.get("po_number"):
        meta.append(("Purchase order", doc["po_number"]))
    for label, value in meta:
        _pair(pdf, label, value, size)

    pdf.section("Request", size)
    pdf.paragraph(doc["request_text"] or "-", size)
    if doc["items"]:
        pdf.paragraph("Items: " + "; ".join(f"{i['description']} x {i['quantity']}" for i in doc["items"]), size - 0.5, "", MUTED)
    if doc["why_a_person"]:
        pdf.section("Why a person was needed", size)
        for reason in doc["why_a_person"]:
            pdf.paragraph("- " + reason, size)

    pdf.section("Offers", size)
    cols = [("Supplier", 38), ("Price", 28), ("Lead time", 20), ("Rating", 14), ("Terms", pdf.width - 38 - 28 - 20 - 14)]
    pdf.set_fill_color(*PINK)
    pdf.set_draw_color(*LINE)
    pdf.set_font("Helvetica", "B", size - 0.5)
    pdf.set_text_color(*INK)
    for text, w in cols:
        pdf.cell(w, size * 0.7, text, border=1, fill=True, new_x="RIGHT", new_y="TOP")
    pdf.ln(size * 0.7)
    for o in doc["offers"]:
        pdf.set_font("Helvetica", "B" if o["chosen"] else "", size - 0.5)
        pdf.set_text_color(*INK)
        pdf.cell(cols[0][1], size * 0.62, (("> " if o["chosen"] else "") + o["supplier"])[:26], border=1, new_x="RIGHT", new_y="TOP")
        pdf.cell(cols[1][1], size * 0.62, o["price"], border=1, new_x="RIGHT", new_y="TOP")
        pdf.cell(cols[2][1], size * 0.62, o["lead_time"], border=1, new_x="RIGHT", new_y="TOP")
        pdf.cell(cols[3][1], size * 0.62, o["reliability"], border=1, new_x="RIGHT", new_y="TOP")
        pdf.cell(cols[4][1], size * 0.62, safe_text(o["terms"])[:38], border=1, new_x="LMARGIN", new_y="NEXT")
        if o["tags"] or o["reason"]:
            pdf.paragraph("   " + " | ".join(x for x in (o["tags"], o["reason"]) if x), size - 1.5, "I", MUTED)
    if doc["offers_left_out"]:
        pdf.paragraph(f"... and {doc['offers_left_out']} more offer(s) not shown.", size - 1.5, "I", MUTED)

    pdf.section("AI recommendation", size)
    if doc.get("ai_pick"):
        pdf.paragraph(f"Recommended supplier: {doc['ai_pick']}", size, "B")
    pdf.paragraph(doc["ai_reasoning"] or "No reasoning was recorded.", size)
    if doc.get("suggestion"):
        pdf.paragraph(doc["suggestion"], size - 0.5, "I", MUTED)

    d = doc["decision"]
    pdf.section("Decision", size)
    pdf.set_fill_color(*PINK)
    pdf.set_font("Helvetica", "B", size + 1)
    pdf.set_text_color(*INK)
    who = f" by {d['by']}" if d["by"] else ""
    when = f" on {d['at']}" if d["at"] else ""
    pdf.multi_cell(pdf.width, (size + 1) * 0.6, safe_text(f"{d['label']}{who}{when}"), fill=True, new_x="LMARGIN", new_y="NEXT")
    if d.get("supplier"):
        pdf.paragraph(f"Supplier chosen: {d['supplier']}" + ("  (not the AI's first choice)" if d["different_from_ai"] else ""), size)
    if d.get("note"):
        pdf.paragraph("Note: " + d["note"], size, "I")
    if pdf.page_no() > 1:
        raise TooLong()
    return pdf


def render_approval_summary(doc: dict) -> bytes:
    for size in (9.5, 8.5, 7.5):
        try:
            return bytes(_draw_summary(doc, size).output())
        except TooLong:
            continue
    raise TooLong("The approval summary does not fit on one page.")
