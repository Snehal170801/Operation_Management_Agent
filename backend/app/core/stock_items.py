"""Stock items: what a person may change about one (name, unit, category, preferred supplier) and when an item may be removed.

Pure rules: no database. The controller gathers the facts (which orders are open, which suppliers exist) and asks these."""

import re

from app.core.exceptions import InvalidInput
from app.core.stock_matching import match_exact

NAME_MAX = 255
UNIT_MAX = 30
CATEGORY_MAX = 60
_UNIT_OK = re.compile(r"^[A-Za-z0-9 ./²³%-]+$")


def clean_name(name) -> str:
    """The item's name with the spaces tidied. It is how requests and orders are matched to stock, so it must say something."""
    text = " ".join(str(name or "").split())
    if not text:
        raise InvalidInput("Give the item a name.")
    if len(text) > NAME_MAX:
        raise InvalidInput(f"The name can be at most {NAME_MAX} characters.")
    return text


def clean_unit(unit) -> str | None:
    """pcs, kg, box, m ... Empty means "not set"."""
    text = " ".join(str(unit or "").split())
    if not text:
        return None
    if len(text) > UNIT_MAX or not _UNIT_OK.match(text):
        raise InvalidInput(f"The unit should be a short word such as pcs, kg, box or m (up to {UNIT_MAX} characters).")
    return text


def clean_category(category) -> str | None:
    text = " ".join(str(category or "").split())
    if not text:
        return None
    if len(text) > CATEGORY_MAX:
        raise InvalidInput(f"The category can be at most {CATEGORY_MAX} characters.")
    return text


def check_rename(new_name: str, current_name: str, all_names: list[str]) -> str:
    """The cleaned new name, refusing one that another item already has (compared without regard to capitals and spaces)."""
    clean = clean_name(new_name)
    key = " ".join(clean.lower().split())
    for other in all_names:
        if " ".join(other.lower().split()) == key and other.lower() != current_name.lower():
            raise InvalidInput(f"There is already a stock item called '{other}'.")
    return clean


def blockers(item_name: str, open_reorders: dict[str, dict], open_request_lines: list[tuple[str, str]]) -> list[str]:
    """Why this item cannot be removed or renamed right now, in words. Empty means it can.
    `open_reorders` is item (lower case) -> {case_number}; `open_request_lines` is (case number, line description) for requests still open."""
    reasons = []
    order = open_reorders.get(item_name.strip().lower())
    if order:
        reasons.append(f"a reorder is on its way ({order.get('case_number') or 'an open request'})")
    seen = {order["case_number"]} if order and order.get("case_number") else set()      # the reorder is already named above
    for number, line in open_request_lines:
        if number in seen or not match_exact(line, [item_name]):
            continue
        seen.add(number)
        reasons.append(f"request {number} is still open and asks for it")
    return reasons


def refusal(item_name: str, action: str, reasons: list[str]) -> str:
    return f"{item_name} cannot be {action} yet: " + "; ".join(reasons) + "."
