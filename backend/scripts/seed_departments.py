"""Create one sign-in per department (each agent's human counterpart), e.g. `purchase`, `receiving`, `accounts`.

    python -m scripts.seed_departments [--password Admin@123]

The Add user screen asks for an email, so these short names are created here. Safe to run again: an account
that already exists is left alone. They start with no email address, so alerts for a department go to the
admins until you add that team's real email (Users -> edit). Change the shared password before real use.
"""

import argparse
import sys
import uuid

from app.controllers.user_controller import _make_private_set
from app.core import access
from app.core.permissions import DEPARTMENTS
from app.core.security import hash_password, validate_password_strength
from app.repositories import user_repository

# department key -> the name people type to sign in
USERNAMES = {
    "purchase": "purchase", "procurement": "stores", "vendor": "vendor", "approval": "approval",
    "po": "po", "delivery": "receiving", "invoice": "accounts",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--password", default="Admin@123", help="the password every account starts with")
    args = parser.parse_args()

    for dept in DEPARTMENTS:
        username = USERNAMES[dept.key]
        if user_repository.find_user_by_identifier(username) is not None:
            print(f"   {username:<10} already exists, left alone")
            continue
        validate_password_strength(args.password, username)
        user_id = str(uuid.uuid4())
        role = _make_private_set(user_id, username, set(dept.permissions))
        user_repository.create_user(
            username=username, password_hash=hash_password(args.password), role=role,
            display_name=dept.label, email=None, user_id=user_id,
        )
        print(f"   {username:<10} created  ({dept.label}: {dept.agent})")
    access.invalidate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
