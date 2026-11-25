"""Tax (GST) on orders and invoices: the lines, and the invoice check. Matching only: nothing here pays or marks anything paid."""

import pytest

from app.core import documents, exports, pdf_render, tax
from app.core.config import settings
from app.core.invoice_policy import evaluate_invoice
from app.orchestrator import case_pipeline

from .fake_world import standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

# ---- the lines ---------------------------------------------------------------------------------------------------------------------------


def test_tax_is_added_on_top_or_taken_out_of_an_included_price():
    assert tax.lines(42000, 18) == {"rate_pct": 18, "subtotal": 42000.0, "tax_amount": 7560.0, "total_with_tax": 49560.0}
    inc = tax.lines(118, 18, included=True)
    assert inc == {"rate_pct": 18, "subtotal": 100.0, "tax_amount": 18.0, "total_with_tax": 118.0}


def test_no_rate_no_price_or_a_negative_rate_means_no_tax_lines():
    assert tax.lines(42000, 0) is None and tax.lines(None, 18) is None and tax.lines(42000, -5) is None


def test_the_order_s_stored_lines_are_read_back_and_an_order_without_them_has_none():
    po = {"tax_rate_pct": 18, "tax_amount": 7560.0, "total_with_tax": 49560.0}
    assert tax.of_order(po) == {"rate_pct": 18, "subtotal": 42000.0, "tax_amount": 7560.0, "total_with_tax": 49560.0}
    assert tax.of_order({}) is None and tax.of_order({"tax_rate_pct": 0, "tax_amount": 0, "total_with_tax": 100}) is None


# ---- the invoice check (pure) -----------------------------------------------------------------------------------------------------------

ORDER = tax.lines(42000, 18)


def check(**invoice):
    return tax.check_invoice(ORDER, {"total_amount": 49560.0, **invoice}, 1.0)


def test_an_invoice_with_the_right_tax_lines_has_no_tax_problem():
    assert check(subtotal=42000.0, tax_rate_pct=18, tax_amount=7560.0) == []
    assert check() == []                                                              # no tax lines shown but the total already includes it
    assert check(subtotal=42000.0, tax_amount=7560.5) == []                           # a rupee of rounding is never a mismatch


def test_a_different_rate_is_a_problem():
    assert any("12%" in p and "18%" in p for p in check(tax_rate_pct=12))


def test_tax_that_is_not_the_rate_of_the_subtotal_or_does_not_add_up_is_a_problem():
    assert any("is not 18% of its subtotal" in p for p in check(subtotal=42000.0, tax_amount=5000.0))
    assert any("does not add up" in p for p in check(subtotal=42000.0, tax_amount=7560.0, total_amount=60000.0))


def test_an_invoice_for_the_price_without_tax_says_so():
    problems = tax.check_invoice(ORDER, {"total_amount": 42000.0}, 1.0)
    assert len(problems) == 1 and "shows no tax" in problems[0] and "49,560.00" in problems[0]


def test_an_order_without_tax_lines_ignores_whatever_the_invoice_says_about_tax():
    assert tax.check_invoice(None, {"total_amount": 100.0, "tax_rate_pct": 99, "tax_amount": 1.0, "subtotal": 5.0}, 1.0) == []


def test_the_policy_collects_the_tax_problems_with_the_others():
    po = {"po_number": "PO-1", "total_amount": 49560.0, "items": []}
    status, problems = evaluate_invoice(po, {"invoice_number": "I", "total_amount": 49560.0, "po_number": "PO-1", "items": [], "tax_rate_pct": 12}, True, False, 1.0, order_tax=ORDER)
    assert status == "mismatch" and any("12%" in p for p in problems)
    assert evaluate_invoice(po, {"invoice_number": "I", "total_amount": 49560.0, "po_number": "PO-1", "items": []}, True, False, 1.0, order_tax=ORDER) == ("matched", [])


# ---- through the pipeline ----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def w(monkeypatch):
    from app.repositories import audit_repository
    monkeypatch.setattr(audit_repository, "insert_entry", lambda *a, **k: None)
    return standard_world(monkeypatch)


def ordered(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    return case_id


def bill(w, case_id, text):
    case_pipeline.confirm_delivery(case_id, "ravi@x.co", None) if w.pos[case_id].delivery_status == "pending" else None
    return w.reply(case_id, "Acme", text, subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")


def test_with_a_tax_rate_set_the_order_carries_the_lines_and_the_supplier_is_told(w, monkeypatch):
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    case_id = ordered(w)
    po = w.pos[case_id]
    assert (po.tax_rate_pct, po.tax_amount, po.total_with_tax) == (18.0, 7560.0, 49560.0)
    body = next(m[2] for m in w.sent if m[0] == "acme@vendor.com" and "Purchase Order" in m[1])
    assert "42,000.00 + tax 7,560.00 (18%) = 49,560.00 with tax" in body


def test_with_no_rate_nothing_about_the_order_changes(w):
    case_id = ordered(w)
    po = w.pos[case_id]
    assert po.tax_rate_pct is None and po.total_with_tax is None
    body = next(m[2] for m in w.sent if m[0] == "acme@vendor.com" and "Purchase Order" in m[1])
    assert "Total amount: 42,000.00" in body and "tax" not in body.lower()


def test_prices_that_already_include_tax_are_split_not_added_to(w, monkeypatch):
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    monkeypatch.setattr(settings, "TAX_INCLUDED_IN_QUOTES", True)
    po = w.pos[ordered(w)]
    assert po.total_with_tax == 42000.0 and po.tax_amount == 6406.78


def test_an_invoice_with_the_right_tax_matches_and_is_never_marked_paid(w, monkeypatch):
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    case_id = ordered(w)
    bill(w, case_id, "Invoice INV-1 for PO-1001. 50 x CCTV camera. Subtotal Rs 42,000. GST 18%. Tax amount Rs 7,560. Total Rs 49,560.")
    invoice = w.invoices[-1]
    assert invoice.status == "matched" and (invoice.subtotal, invoice.tax_rate_pct, invoice.tax_amount) == (42000.0, 18.0, 7560.0)
    assert not [e for e in w.event_types(case_id) if "paid" in e or "payment" in e]


def test_an_invoice_for_the_price_without_tax_is_a_mismatch_and_accounts_are_told(w, monkeypatch):
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    case_id = ordered(w)
    bill(w, case_id, "Invoice INV-2 for PO-1001. 50 x CCTV camera. Total Rs 42,000.")
    assert w.invoices[-1].status == "mismatch" and "shows no tax" in w.invoices[-1].issues
    assert [m for m in w.emails_to("manager@x.co") if "does not match" in m[2] and "shows no tax" in m[2]]


def test_an_invoice_at_another_tax_rate_is_a_mismatch(w, monkeypatch):
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    case_id = ordered(w)
    bill(w, case_id, "Invoice INV-3 for PO-1001. 50 x CCTV camera. Subtotal Rs 42,000. GST 12%. Tax amount Rs 5,040. Total Rs 47,040.")
    invoice = w.invoices[-1]
    assert invoice.status == "mismatch" and any("12%" in x and "18%" in x for x in __import__("json").loads(invoice.issues))


def test_the_old_behaviour_is_unchanged_when_tax_is_off_even_if_the_invoice_mentions_gst(w):
    case_id = ordered(w)
    bill(w, case_id, "Invoice INV-4 for PO-1001. 50 x CCTV camera. GST 18%. Tax amount Rs 7,560. Total Rs 42,000.")
    assert w.invoices[-1].status == "matched"


# ---- documents and exports ---------------------------------------------------------------------------------------------------------------

def test_the_order_document_shows_the_tax_lines_only_when_there_are_some():
    base = {"po_number": "PO-1", "vendor_name": "Acme", "total_amount": 42000.0, "items": [], "status": "sent"}
    plain = documents.purchase_order(base, None, {"name": "Co"}, "REQ-1", "ravi")
    taxed = documents.purchase_order({**base, "tax_rate_pct": 18.0, "tax_amount": 7560.0, "total_with_tax": 49560.0}, None, {"name": "Co"}, "REQ-1", "ravi")
    assert plain["tax"] is None and taxed["tax"] == {"subtotal": "Rs 42,000.00", "rate": "18%", "amount": "Rs 7,560.00", "total": "Rs 49,560.00"}
    from pypdf import PdfReader
    import io
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf_render.render_purchase_order(taxed))).pages)
    assert "Tax (18%)" in text and "Total with tax" in text and "49,560.00" in text


def test_the_exports_carry_the_tax_columns():
    assert "Tax" in exports.COLUMNS["purchase-orders"] and "Tax shown" in exports.COLUMNS["invoices"]
    row = exports.purchase_order_rows([{"po_number": "PO-1", "case_id": "c", "vendor_name": "A", "total_amount": 1.0, "tax_amount": 0.18, "total_with_tax": 1.18, "status": "sent"}], {"c": "REQ-1"})[0]
    assert len(row) == len(exports.COLUMNS["purchase-orders"])
    irow = exports.invoice_rows([{"po_number": "PO-1", "case_id": "c", "vendor_name": "A", "total_amount": 1.0, "tax_amount": 0.18, "status": "matched"}], {"c": "REQ-1"})[0]
    assert len(irow) == len(exports.COLUMNS["invoices"])


def test_the_rate_is_a_setting_with_a_sane_range():
    from app.core import tunables
    keys = {t.key: t for t in tunables.CATALOG}
    assert keys["TAX_RATE_PCT"].group == "invoice" and tunables.DEFAULTS["TAX_RATE_PCT"] == 0 and tunables.DEFAULTS["TAX_INCLUDED_IN_QUOTES"] is False
    assert tunables.validate({"TAX_RATE_PCT": 18}) == {"TAX_RATE_PCT": 18.0}
    with pytest.raises(tunables.InvalidSetting):
        tunables.validate({"TAX_RATE_PCT": 150})


# ---- the limits are about what it really costs: with tax ---------------------------------------------------------------------------------

def test_cost_is_the_price_with_tax_and_the_same_price_when_no_rate_is_set():
    assert tax.cost(45000, 18) == 53100.0 and tax.cost(45000, 0) == 45000 and tax.cost(None, 18) is None
    assert tax.cost(118, 18, included=True) == 118.0                                   # already includes it: the cost is the price


def test_the_auto_approve_limit_uses_the_amount_with_tax(monkeypatch):
    from app.core.approval_policy import human_review_reasons
    quote = {"price": 45000.0}
    monkeypatch.setattr(settings, "AUTO_APPROVE_MAX_AMOUNT", 50000.0)
    monkeypatch.setattr(settings, "AUTO_APPROVE_DAILY_LIMIT", 10_000_000.0)
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 0.0)
    assert human_review_reasons(quote, 4.5, 3) == []                                     # no rate: nothing changes
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    reasons = human_review_reasons(quote, 4.5, 3)
    assert len(reasons) == 1 and "53,100.00 with tax" in reasons[0] and "auto-approve limit" in reasons[0]
    monkeypatch.setattr(settings, "TAX_INCLUDED_IN_QUOTES", True)                          # the 45,000 already contains the tax: under the limit
    assert human_review_reasons(quote, 4.5, 3) == []


def test_the_daily_spend_cap_uses_the_amount_with_tax(monkeypatch):
    from app.core.approval_policy import human_review_reasons
    monkeypatch.setattr(settings, "AUTO_APPROVE_MAX_AMOUNT", 1_000_000.0)
    monkeypatch.setattr(settings, "AUTO_APPROVE_DAILY_LIMIT", 100_000.0)
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 0.0)
    assert human_review_reasons({"price": 40000.0}, 4.5, 3, spent_today=55000.0) == []                     # 95,000 <= 100,000
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    reasons = human_review_reasons({"price": 40000.0}, 4.5, 3, spent_today=55000.0)                        # 55,000 + 47,200 = 102,200
    assert len(reasons) == 1 and "102,200.00" in reasons[0] and "daily limit" in reasons[0]


def test_the_one_tap_amount_and_the_email_limit_use_the_amount_with_tax(w, monkeypatch):
    from app.controllers import decision_controller
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    monkeypatch.setattr(settings, "EMAIL_APPROVE_ENABLED", True)
    monkeypatch.setattr(settings, "EMAIL_APPROVE_MAX_AMOUNT", 50000.0)
    review = type("R", (), {"options": [type("O", (), {"vendor_id": "a", "price": 45000.0})()], "selected_vendor_id": "a", "kind": "vendor_selection", "price_change": None})()
    assert decision_controller._within_limit(review) is False                              # 53,100 > 50,000: the buttons are not offered
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 0.0)
    assert decision_controller._within_limit(review) is True


def test_a_quote_just_under_the_limit_reaches_a_person_once_tax_is_counted(w, monkeypatch):
    monkeypatch.setattr(settings, "TAX_RATE_PCT", 18.0)
    case_id = w.submit("50 cameras")
    for name, price in (("Acme", "45,000"), ("Globex", "46,000")):
        w.reply(case_id, name, f"Total Rs {price}. Delivery 7 days. Terms: net 30")
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval"                                          # 53,100 with tax is over the 50,000 limit
