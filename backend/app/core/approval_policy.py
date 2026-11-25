"""
Decides whether a vendor selection can proceed automatically or needs a human.
Returns the list of reasons a human is needed; an empty list means auto-approve.
Pure function -- no DB or LLM -- so the rules are easy to test and change.
"""

from app.core import tax
from app.core.config import settings


RESTOCK_REASON = "This is a low-stock reorder. Every reorder needs an approver's OK, whatever the amount."


def human_review_reasons(selected_quote: dict | None, reliability_score: float | None,
                         quote_count: int, spent_today: float = 0.0, restock: bool = False) -> list[str]:
    reasons = []
    if restock:
        reasons.append(RESTOCK_REASON)          # a reorder is raised by Stores or an admin; spending on it is always approved by someone else

    if selected_quote is None or selected_quote.get("price") is None:
        reasons.append("Selected vendor's quote has no readable price.")
    else:
        # With a tax rate set, the limits are about the real cost: the price WITH tax (the same price when no rate is set).
        amount = tax.cost(selected_quote["price"], settings.TAX_RATE_PCT, settings.TAX_INCLUDED_IN_QUOTES)
        with_tax = " with tax" if amount != selected_quote["price"] else ""
        if amount > settings.AUTO_APPROVE_MAX_AMOUNT:
            reasons.append(
                f"Amount {amount:,.2f}{with_tax} exceeds the auto-approve limit "
                f"of {settings.AUTO_APPROVE_MAX_AMOUNT:,.2f}."
            )
        elif spent_today + amount > settings.AUTO_APPROVE_DAILY_LIMIT:
            reasons.append(
                f"Approving this automatically would take today's automatic spend to "
                f"{spent_today + amount:,.2f}{with_tax}, above the daily limit of "
                f"{settings.AUTO_APPROVE_DAILY_LIMIT:,.2f}."
            )

    if reliability_score is None or reliability_score < settings.AUTO_APPROVE_MIN_RELIABILITY:
        reasons.append(
            f"Vendor reliability {reliability_score} is below the required "
            f"{settings.AUTO_APPROVE_MIN_RELIABILITY}."
        )

    if quote_count < settings.AUTO_APPROVE_MIN_QUOTES:
        reasons.append(
            f"Only {quote_count} quote(s) received; at least "
            f"{settings.AUTO_APPROVE_MIN_QUOTES} are needed to auto-approve."
        )

    return reasons
