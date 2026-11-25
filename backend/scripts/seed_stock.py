"""Add (or reset) sample stock for testing. Safe to re-run: each item is set to the quantity in
scripts/stock_catalog.py, so running it again puts the sample items back to their starting levels.

    python -m scripts.seed_stock
"""

import sys

from app.repositories import stock_repository
from scripts.stock_catalog import STOCK


def main() -> int:
    for description, quantity in STOCK:
        stock_repository.upsert_stock(description, quantity)
    print(f"Set {len(STOCK)} stock item(s):")
    for description, quantity in STOCK:
        print(f"  {description:<32} {quantity}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
