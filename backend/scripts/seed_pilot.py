"""Set up a pilot database with sample accounts, suppliers and stock. Safe to re-run.

Simplest, with ONE email address for everything:

    python -m scripts.seed_pilot --single-mailbox you@gmail.com

  * three sign-in accounts: usernames `admin`, `manager` and `ravi` (role user), one shared password
  * only `manager` carries your email, so approval/stalled alerts arrive in your inbox
  * the three suppliers all use your email, so every "supplier" email arrives in your own inbox and
    YOU play the suppliers (enter their quotes by hand on the case page)

With separate addresses (plus-addresses such as you+admin@gmail.com work too):

    python -m scripts.seed_pilot --admin you+admin@co.com --manager you+manager@co.com \\
        --user you+ravi@co.com --vendor-mailbox you@co.com

Also loads sample stock (laptops, monitors, phones, fans, AC, CCTV, ... see scripts/stock_catalog.py).
Use a SEPARATE pilot database if you can.
"""

import argparse
import getpass
import sys

from app.core.exceptions import WeakPassword
from app.core.security import hash_password, validate_password_strength
from app.repositories import stock_repository, user_repository, vendor_repository
from scripts.stock_catalog import STOCK

# (name, reliability 0-5): two suppliers trusted enough for automatic approval, one not.
VENDORS = (("Acme Supplies", 4.5), ("Globex Traders", 4.2), ("Initech Imports", 3.0))


def plus_address(mailbox: str, tag: str) -> str:
    """pilot@co.com + 'acme' -> pilot+acme@co.com (delivered to the same inbox)."""
    local, _, domain = mailbox.strip().partition("@")
    if not local or not domain:
        raise ValueError(f"'{mailbox}' is not an email address")
    slug = "".join(ch for ch in tag.lower() if ch.isalnum())
    return f"{local}+{slug}@{domain}"


def _vendor_slug(name: str) -> str:
    return name.split()[0]


def _check_address(value: str) -> str:
    plus_address(value, "x")  # raises ValueError if it is not an address
    return value.strip().lower()


def plan(args) -> tuple[list[tuple[str, str, str, str | None]], dict[str, str]]:
    """What to create: accounts as (username, role, display name, email) and supplier emails by name.
    Pure (no database), so the two modes are easy to test."""
    if args.single_mailbox:
        mailbox = _check_address(args.single_mailbox)
        accounts = [
            ("admin", "admin", "Pilot Admin", None),
            ("manager", "manager", "Pilot Manager", mailbox),     # the one that gets alerts
            ("ravi", "user", "Pilot Requester", None),
        ]
        return accounts, {name: mailbox for name, _ in VENDORS}

    missing = [flag for flag, value in (("--admin", args.admin), ("--manager", args.manager),
                                        ("--user", args.user), ("--vendor-mailbox", args.vendor_mailbox)) if not value]
    if missing:
        raise ValueError(f"give {', '.join(missing)} (or use --single-mailbox you@example.com for one address)")
    accounts = [
        (_check_address(args.admin), "admin", "Pilot Admin", _check_address(args.admin)),
        (_check_address(args.manager), "manager", "Pilot Manager", _check_address(args.manager)),
        (_check_address(args.user), "user", "Pilot Requester", _check_address(args.user)),
    ]
    return accounts, {name: plus_address(args.vendor_mailbox, _vendor_slug(name)) for name, _ in VENDORS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--single-mailbox", help="use this one email address for everything (simplest)")
    parser.add_argument("--admin", help="email for the admin account")
    parser.add_argument("--manager", help="email for the manager account (gets approval alerts)")
    parser.add_argument("--user", help="email for the requester account")
    parser.add_argument("--vendor-mailbox", help="an inbox you can read; supplier emails are plus-addresses of it")
    parser.add_argument("--password", help="password for all three accounts (prompted if omitted)")
    args = parser.parse_args()

    try:
        accounts, supplier_emails = plan(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    password = args.password or getpass.getpass("Password for the three pilot accounts: ")
    try:
        for username, _, _, _ in accounts:
            validate_password_strength(password, username)
    except WeakPassword as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for username, role, label, email in accounts:
        created = user_repository.upsert_user(
            username=username, password_hash=hash_password(password), role=role,
            display_name=label, email=email,
        )
        print(f"{'Created' if created else 'Updated'} {role}: sign in as '{username}'"
              + (f" (alerts go to {email})" if email else ""))

    for name, reliability in VENDORS:
        vendor_repository.upsert_vendor(name, reliability, supplier_emails[name])
        print(f"Supplier: {name} (reliability {reliability}) -> {supplier_emails[name]}")

    for description, quantity in STOCK:
        stock_repository.upsert_stock(description, quantity)
    print(f"Stock: {len(STOCK)} sample item(s) loaded")

    print("\nDone. Next: python -m scripts.preflight, then follow docs/PILOT_WALKTHROUGH.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
