"""Tax (GST) on purchase orders and invoices: working out the lines, and checking an invoice against them. MATCHING ONLY: nothing here pays or
marks anything paid; a mismatch is shown to Accounts, who decide.

Pure functions: no database, clock or AI. Switched off by default (rate 0): then nothing about orders and invoices changes.
"""


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def lines(total: float | None, rate_pct: float, included: bool = False) -> dict | None:
    """The tax lines of an order whose agreed price is `total`. `included` says the price already contains the tax (the tax is then part of it);
    otherwise the tax is added on top. None when tax is not modelled (rate 0) or there is no price.
    Returns {rate_pct, subtotal, tax_amount, total_with_tax}."""
    if total is None or not rate_pct or rate_pct <= 0:
        return None
    if included:
        subtotal = _money(total / (1 + rate_pct / 100))
        return {"rate_pct": rate_pct, "subtotal": subtotal, "tax_amount": _money(total - subtotal), "total_with_tax": _money(total)}
    tax = _money(total * rate_pct / 100)
    return {"rate_pct": rate_pct, "subtotal": _money(total), "tax_amount": tax, "total_with_tax": _money(total + tax)}


def cost(price: float | None, rate_pct: float, included: bool = False) -> float | None:
    """What an order really costs: the price WITH tax when tax is tracked, otherwise the price as it is. The approval limits and the daily
    spend cap use this, so a limit is never passed by the tax. Same as `price` when no rate is set."""
    lines_ = lines(price, rate_pct, included)
    return lines_["total_with_tax"] if lines_ else price


def of_order(po: dict) -> dict | None:
    """The order's tax lines as stored on it, or None when it has none."""
    rate, tax, whole = po.get("tax_rate_pct"), po.get("tax_amount"), po.get("total_with_tax")
    if not rate or rate <= 0 or tax is None or whole is None:
        return None
    return {"rate_pct": rate, "subtotal": _money(whole - tax), "tax_amount": tax, "total_with_tax": whole}


def _near(a: float, b: float, tolerance_pct: float) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * tolerance_pct / 100)       # a rupee of rounding is never a mismatch


def check_invoice(order_tax: dict | None, invoice: dict, tolerance_pct: float) -> list[str]:
    """Problems with the TAX on an invoice for an order that has tax lines (the total itself is compared elsewhere). Nothing when the order has no
    tax lines: tax is then not modelled. The invoice's own fields are subtotal, tax_rate_pct, tax_amount and total_amount (each may be missing)."""
    if order_tax is None:
        return []
    problems: list[str] = []
    rate, tax, subtotal, total = invoice.get("tax_rate_pct"), invoice.get("tax_amount"), invoice.get("subtotal"), invoice.get("total_amount")
    expected_rate = order_tax["rate_pct"]
    if rate is not None and abs(rate - expected_rate) > 0.01:
        problems.append(f"The invoice charges tax at {rate:g}% but the order is at {expected_rate:g}%.")
    use_rate = rate if rate is not None else expected_rate
    if tax is not None and subtotal is not None and not _near(tax, subtotal * use_rate / 100, tolerance_pct):
        problems.append(f"The tax on the invoice ({tax:,.2f}) is not {use_rate:g}% of its subtotal ({subtotal:,.2f}).")
    if tax is not None and subtotal is not None and total is not None and not _near(subtotal + tax, total, tolerance_pct):
        problems.append(f"The invoice's subtotal ({subtotal:,.2f}) plus tax ({tax:,.2f}) does not add up to its total ({total:,.2f}).")
    if tax is None and rate is None and subtotal is None and total is not None \
            and _near(total, order_tax["subtotal"], tolerance_pct) and not _near(total, order_tax["total_with_tax"], tolerance_pct):
        problems.append(f"The invoice shows no tax. The order is {order_tax['subtotal']:,.2f} plus {order_tax['tax_amount']:,.2f} tax = {order_tax['total_with_tax']:,.2f}.")
    return problems


def text(order_tax: dict | None, currency: str = "") -> str:
    """One line for an e-mail: 'Subtotal 100.00, GST 18% 18.00, total 118.00'."""
    if order_tax is None:
        return ""
    return (f"Subtotal: {currency}{order_tax['subtotal']:,.2f}\nTax ({order_tax['rate_pct']:g}%): {currency}{order_tax['tax_amount']:,.2f}\n"
            f"Total with tax: {currency}{order_tax['total_with_tax']:,.2f}")
