"""
Three-way match of a vendor invoice against the purchase order and the goods receipt.
Pure function -- no DB, LLM or clock access -- so the rules are easy to test and change.

Returns (status, issues):
  "matched"  -> everything agrees and the goods are received: safe to pass for payment
  "on_hold"  -> nothing is wrong, but the goods are not confirmed received yet
  "mismatch" -> something disagrees (or is unreadable): a person must decide
"""

from app.core import tax as tax_rules


def _within(total: float, expected: float, tolerance_pct: float) -> bool:
    return abs(total - expected) <= abs(expected) * tolerance_pct / 100


def evaluate_invoice(po: dict, invoice: dict, goods_received: bool, is_duplicate: bool,
                     tolerance_pct: float, partial: dict | None = None, order_tax: dict | None = None) -> tuple[str, list[str]]:
    """`partial` is given only for an order delivered in parts (see core/partial_delivery.py):
    {"received_units", "ordered_units", "invoiced_so_far", "closed_short"}. A supplier may then bill the whole balance
    (held until everything is in) or just what has arrived so far (cleared now). Without it nothing changes."""
    problems: list[str] = []
    bills_part = False

    if is_duplicate:
        problems.append(f"Invoice {invoice['invoice_number']} was already submitted by this vendor (possible duplicate).")

    if not invoice.get("invoice_number"):
        problems.append("The invoice number could not be read.")

    total = invoice.get("total_amount")
    if total is None:
        problems.append("The invoice total could not be read.")
    elif po["total_amount"] is None:
        problems.append("The purchase order has no agreed total to compare the invoice against.")
    elif partial:
        owed = po["total_amount"] - partial["invoiced_so_far"]                       # the whole balance
        arrived = po["total_amount"] * partial["received_units"] / max(1, partial["ordered_units"]) - partial["invoiced_so_far"]   # what has arrived and is not yet billed
        whole_ok = not partial["closed_short"] and _within(total, owed, tolerance_pct)
        bills_part = not whole_ok and arrived > 0 and _within(total, arrived, tolerance_pct)
        if not whole_ok and not bills_part:
            expected = f"{arrived:,.2f} for what has arrived so far" + ("" if partial["closed_short"] else f", or {owed:,.2f} for the whole balance")
            problems.append(f"Invoice total {total:,.2f} does not match what is owed ({expected}).")
    else:
        allowed = abs(po["total_amount"]) * tolerance_pct / 100
        if abs(total - po["total_amount"]) > allowed:
            problems.append(
                f"Invoice total {total:,.2f} differs from the purchase order total {po['total_amount']:,.2f}."
            )

    problems.extend(tax_rules.check_invoice(order_tax, invoice, tolerance_pct))        # (the caller passes the order's total WITH tax in `po` when tax is tracked)

    quoted_po = invoice.get("po_number")
    if quoted_po and quoted_po.strip().upper() != po["po_number"].upper():
        problems.append(f"The invoice quotes {quoted_po}, but this case's order is {po['po_number']}.")

    invoice_items = invoice.get("items") or []
    if invoice_items and not (partial and partial["invoiced_so_far"] > 0):          # (a later invoice cannot be counted item by item)
        invoiced = sum(i["quantity"] for i in invoice_items)
        ordered = partial["received_units"] if bills_part else sum(i["quantity"] for i in po["items"])
        if invoiced != ordered:
            problems.append(f"The invoice bills {invoiced} item(s) but {ordered} {'have arrived' if bills_part else 'were ordered'}.")

    if problems:
        return "mismatch", problems
    if bills_part:
        return "matched", []                      # billing for what has arrived: fine to clear now; the order stays open for the rest
    if not goods_received:
        return "on_hold", ["Waiting for the goods to be confirmed as received."]
    return "matched", []
