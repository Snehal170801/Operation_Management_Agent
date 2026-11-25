"""Preferred suppliers: a supplier can be marked as preferred for a stock item, and then is always asked when a request includes that item.

Today every supplier who can be reached is asked for a quote on every request, and that stays exactly as it is. A preferred supplier adds two
things on top: they are asked first, and when a preferred supplier CANNOT be asked (no e-mail address, or one that bounces) a person is told,
instead of the request quietly going out without them. A supplier a person has just turned down (the one skipped on a new round) is still not
asked again: "always" never overrides an explicit decision.

Pure functions: no database, no e-mail."""


def reachable(vendor: dict) -> bool:
    """Has an e-mail address that is not known to bounce."""
    return bool(vendor.get("email")) and not vendor.get("email_bounced_at")


def _ids(preferred_ids) -> set[str]:
    return {str(p).lower() for p in (preferred_ids or ())}


def order_for_asking(vendors: list[dict], preferred_ids) -> list[dict]:
    """The same suppliers, preferred ones first (the order within each group is kept). Nobody is added or dropped."""
    preferred = _ids(preferred_ids)
    return sorted(vendors, key=lambda v: 0 if str(v["vendor_id"]).lower() in preferred else 1)


def unreachable_preferred(vendors: list[dict], preferred_ids, skip_vendor_id: str | None = None) -> list[str]:
    """Names of preferred suppliers who cannot be asked (a supplier deliberately skipped is not counted: that was a decision)."""
    preferred, skip = _ids(preferred_ids), (skip_vendor_id or "").lower()
    return [v["name"] for v in vendors
            if str(v["vendor_id"]).lower() in preferred and str(v["vendor_id"]).lower() != skip and not reachable(v)]
