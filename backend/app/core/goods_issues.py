"""Wrong or damaged goods: Receiving records the problem, the supplier is asked to put it right, the invoice is held until it is.

An issue is open until a person records how it ended:
  replaced   the supplier replaced the faulty goods (nothing to pay differently)
  credit     the supplier gives money back: a credit of an agreed amount comes off what the invoice may bill
  accepted   we keep the goods as they are, no change to what is owed

Pure functions: no database or clock.
"""

KINDS = {
    "damaged": "arrived damaged",
    "wrong_item": "is not what was ordered",
    "not_as_described": "does not match the specification",
    "other": "has a problem",
}
RESOLUTIONS = ("replaced", "credit", "accepted")
OPEN, RESOLVED = "open", "resolved"
DESCRIPTION_MAX = 500


class BadIssue(ValueError):
    """The report or the resolution cannot be right."""


def _key(name: str) -> str:
    return " ".join(str(name).lower().split())


def validate_report(po_items: list[dict], received_by_item: dict[str, int], kind: str, items: dict[str, int] | None, description: str | None) -> tuple[list[dict], str | None]:
    """The affected items as [{"description", "quantity"}] (the order's own names) and the cleaned description.
    `received_by_item` is what has actually arrived (lower-case name -> quantity): only goods that arrived can be faulty.
    `items` None means "everything that arrived"."""
    if kind not in KINDS:
        raise BadIssue(f"Choose what is wrong: {', '.join(KINDS)}.")
    arrived = {_key(i["description"]): (i["description"], received_by_item.get(_key(i["description"]), 0)) for i in po_items}
    if not any(q for _, q in arrived.values()):
        raise BadIssue("Nothing has been recorded as received yet, so there is nothing to report a problem with.")
    if items is None:
        affected = [{"description": name, "quantity": q} for name, q in arrived.values() if q > 0]
    else:
        affected = []
        for name, qty in items.items():
            known = arrived.get(_key(name))
            if known is None:
                raise BadIssue(f"'{name}' is not on this order.")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
                raise BadIssue(f"The number of {known[0]} affected must be a whole number, 1 or more.")
            if qty > known[1]:
                raise BadIssue(f"Only {known[1]} of {known[0]} have arrived, so {qty} cannot be faulty.")
            affected.append({"description": known[0], "quantity": qty})
        if not affected:
            raise BadIssue("Say which items are affected.")
    text = (description or "").strip()[:DESCRIPTION_MAX] or None
    if kind == "other" and not text:
        raise BadIssue("Describe the problem.")
    return affected, text


def validate_resolution(resolution: str, credit_amount, order_total: float | None) -> float | None:
    """The credit to record (None unless the resolution is a credit)."""
    if resolution not in RESOLUTIONS:
        raise BadIssue(f"Choose how it ended: {', '.join(RESOLUTIONS)}.")
    if resolution != "credit":
        return None
    if isinstance(credit_amount, bool) or not isinstance(credit_amount, (int, float)) or credit_amount <= 0:
        raise BadIssue("Enter the amount of the credit.")
    if order_total is not None and credit_amount > order_total:
        raise BadIssue("The credit cannot be more than the whole order.")
    return round(float(credit_amount), 2)


RETURNED, REPLACEMENT_EXPECTED, REPLACEMENT_RECEIVED = "returned", "expected", "received"
REF_MAX = 100


def clean_ref(value) -> str | None:
    """A return reference, credit note number or similar: short plain text, empty means none."""
    text = " ".join(str(value or "").split())
    if len(text) > REF_MAX:
        raise BadIssue(f"Keep the reference to {REF_MAX} characters or fewer.")
    return text or None


def progress(issue: dict) -> str:
    """Where an issue is, in one word: reported | returned | replacement_expected | replacement_received | resolved."""
    if issue["status"] != OPEN:
        return "resolved"
    if issue.get("replacement_status") == REPLACEMENT_EXPECTED:
        return "replacement_expected"
    if issue.get("return_status") == RETURNED:
        return "returned"
    return "reported"


def check_can_return(issue: dict) -> None:
    if issue["status"] != OPEN:
        raise BadIssue("This problem has already been closed.")
    if issue.get("return_status") == RETURNED:
        raise BadIssue("The goods have already been marked as returned.")


def check_can_expect_replacement(issue: dict) -> None:
    if issue["status"] != OPEN:
        raise BadIssue("This problem has already been closed.")
    if issue.get("replacement_status"):
        raise BadIssue("A replacement is already expected for this problem.")


def check_can_receive_replacement(issue: dict) -> None:
    if issue["status"] != OPEN:
        raise BadIssue("This problem has already been closed.")
    if issue.get("replacement_status") != REPLACEMENT_EXPECTED:
        raise BadIssue("No replacement is expected yet: record that the supplier will replace the goods first.")


def return_notice(vendor: str, po_number: str, items: list[dict], ref: str | None) -> str:
    return (f"Dear {vendor},\n\nAs discussed, we are returning the following goods from purchase order {po_number}:\n\n  {affected_text(items)}\n\n"
            f"{'Our return reference: ' + ref + chr(10) + chr(10) if ref else ''}"
            f"Please confirm when you have them, and tell us whether you will send replacements or a credit note.\n\nThank you.")


def credit_message(issue: dict) -> str:
    """For Accounts: a credit was agreed. They apply it by hand; nothing owed is changed automatically."""
    note = f" (credit note {issue['credit_note_number']})" if issue.get("credit_note_number") else ""
    return (f"{issue['vendor_name']} agreed a credit of {issue['credit_amount']:,.2f}{note} on {issue['po_number']} for {affected_text(issue['items'])}. "
            f"Please apply it by hand when paying. Nothing you owe was changed automatically.")


def credit_total(issues: list[dict]) -> float:
    """Money the supplier has agreed to give back on this order."""
    return round(sum(float(i.get("credit_amount") or 0) for i in issues if i["status"] == RESOLVED and i.get("resolution") == "credit"), 2)


def open_issues(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["status"] == OPEN]


def affected_text(items: list[dict]) -> str:
    return ", ".join(f"{i['description']} × {i['quantity']}" for i in items)


def supplier_message(vendor: str, po_number: str, kind: str, items: list[dict], description: str | None) -> str:
    return (
        f"Dear {vendor},\n\nWe have received part or all of purchase order {po_number}, but there is a problem: the following "
        f"{KINDS[kind]}:\n\n  {affected_text(items)}\n\n{description + chr(10) + chr(10) if description else ''}"
        f"Please reply to tell us how you will put this right: replace the affected items at no charge, or issue a credit note. "
        f"We will hold payment for this order until it is sorted out.\n\nThank you."
    )
