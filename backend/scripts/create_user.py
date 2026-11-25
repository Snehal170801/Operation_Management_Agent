"""Create a user, or reset an existing user's password (which also signs them out everywhere).

    python -m scripts.create_user you@example.com --role admin --display-name "Administrator"
    python -m scripts.create_user you@example.com --password "..."        # non-interactive

Without --password you are prompted (input is hidden).
"""

import argparse
import getpass
import sys

from app.core.exceptions import WeakPassword
from app.core.security import hash_password, validate_password_strength
from app.repositories import user_repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", help="the sign-in email (also stored as the username)")
    parser.add_argument("--password")
    parser.add_argument("--role", choices=["admin", "manager", "viewer", "user"], default="user")
    parser.add_argument("--display-name")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    try:
        validate_password_strength(password, args.email)
    except WeakPassword as exc:
        print(str(exc), file=sys.stderr)
        return 1

    created = user_repository.upsert_user(
        username=args.email.strip().lower(),
        password_hash=hash_password(password),
        role=args.role,
        display_name=args.display_name,
        email=args.email.strip().lower(),
    )
    print(f"{'Created' if created else 'Updated'} {args.role} '{args.email}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
