"""Apply pending SQL migrations from backend/migrations to SQL_DATABASE.

    python -m scripts.migrate

Applied files are recorded in dbo.SchemaMigrations, so it is safe to re-run.
Scripts are split on lines that contain only GO.
"""

import re
import sys
from pathlib import Path

from app.db.connection import get_connection

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _batches(sql: str) -> list[str]:
    parts = re.split(r"^\s*GO\s*$", sql, flags=re.IGNORECASE | re.MULTILINE)
    return [p.strip() for p in parts if p.strip()]


def main() -> int:
    conn = get_connection()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "IF OBJECT_ID('dbo.SchemaMigrations', 'U') IS NULL "
            "CREATE TABLE dbo.SchemaMigrations ("
            "filename NVARCHAR(200) NOT NULL PRIMARY KEY, "
            "applied_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
        )
        cur.execute("SELECT filename FROM dbo.SchemaMigrations")
        applied = {row.filename for row in cur.fetchall()}

        pending = [f for f in sorted(MIGRATIONS_DIR.glob("*.sql")) if f.name not in applied]
        if not pending:
            print("Database is up to date.")
            return 0

        for path in pending:
            print(f"Applying {path.name} ...")
            for batch in _batches(path.read_text(encoding="utf-8")):
                cur.execute(batch)
            cur.execute("INSERT INTO dbo.SchemaMigrations (filename) VALUES (?)", path.name)
        print(f"Applied {len(pending)} migration(s).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
