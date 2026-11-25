"""The safe end-to-end test environment: its own database, a folder instead of a mailbox, a stand-in for the AI.

    python -m scripts.e2e_env reset-db     drop and re-create the test database (only ever opetional_agents_test)
    python -m scripts.e2e_env migrate      create the tables
    python -m scripts.e2e_env seed         fixed accounts, suppliers and stock
    python -m scripts.e2e_env reset-mail   empty the test mailbox folder
    python -m scripts.e2e_env serve        run the API on the test port (default 8100)

Every command first FORCES the safe settings into the process environment, whatever backend/.env says (a variable that is
already set, even to an empty string, wins over .env). Nothing here can reach the real database, a real mailbox or the real AI.
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
RUNTIME = REPO / "frontend" / "e2e" / ".runtime"

TEST_DATABASE = "opetional_agents_test"
API_PORT = int(os.environ.get("E2E_API_PORT", "8100"))
WEB_PORT = int(os.environ.get("E2E_WEB_PORT", "5190"))
MAIL_DIR = Path(os.environ.get("E2E_MAIL_DIR", str(RUNTIME / "mail")))
PASSWORD = "E2eTest@2026!"  # every seeded account (also the departments)

# username -> (role, display name, email). Departments are added by scripts.seed_departments.
ACCOUNTS = (
    ("admin", "admin", "E2E Admin", "admin@e2e.test"),
    ("manager", "manager", "E2E Manager", "manager@e2e.test"),
    ("requester", "user", "E2E Requester", "requester@e2e.test"),
    ("requester2", "user", "E2E Requester Two", "requester2@e2e.test"),
)
# name, reliability (0-5), email: two trusted suppliers and one that is not (see the approval policy).
VENDORS = (
    ("Acme Supplies", 4.5, "acme@supplier.test"),
    ("Globex Traders", 4.2, "globex@supplier.test"),
    ("Initech Imports", 3.0, "initech@supplier.test"),
)

# Forced values. The blank ones keep a real mailbox / Azure unreachable even if .env fills them in.
FORCED = {
    "SQL_DATABASE": TEST_DATABASE,
    "ENVIRONMENT": "development",
    "TEST_MAIL_DIR": str(MAIL_DIR),
    "TEST_AI_STUB": "true",
    "CALL_AFTER_EMAIL": "false",
    "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
    "IMAP_HOST": "", "IMAP_USER": "", "IMAP_PASSWORD": "",
    "AZURE_OPENAI_API_KEY": "", "AZURE_OPENAI_ENDPOINT": "",
    "TWILIO_ACCOUNT_SID": "", "TWILIO_AUTH_TOKEN": "", "EXOTEL_ACCOUNT_SID": "", "EXOTEL_API_KEY": "", "EXOTEL_API_TOKEN": "",
    "APP_BASE_URL": f"http://localhost:{WEB_PORT}",
    "CORS_ORIGINS": f"http://localhost:{WEB_PORT}",
    "CORS_ORIGIN_REGEX": "",
    "COOKIE_SECURE": "false",
    "WORKER_ENABLED": "true",
    "WORKER_INTERVAL_SECONDS": "2",
    "ALLOW_OPEN_ACCOUNT": "true",
}


def apply_env() -> None:
    """Must run before anything imports app.core.config."""
    if "app.core.config" in sys.modules:
        raise RuntimeError("app.core.config was imported before the test settings were applied")
    os.environ.update(FORCED)
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")  # fills in only what is not set (SQL server name, driver, JWT secret ...)
    os.environ["SQL_DATABASE"] = TEST_DATABASE  # belt and braces
    assert os.environ["SQL_DATABASE"].endswith("_test")


def _master_connection():
    import pyodbc
    conn_str = (f"DRIVER={os.environ['SQL_DRIVER']};SERVER={os.environ['SQL_SERVER']};DATABASE=master;"
                f"Trusted_Connection={os.environ['SQL_TRUSTED_CONNECTION']};")
    return pyodbc.connect(conn_str, autocommit=True, timeout=15)


def reset_db() -> None:
    assert TEST_DATABASE == "opetional_agents_test" and TEST_DATABASE.endswith("_test")
    conn = _master_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DB_ID(?)", TEST_DATABASE)
        if cur.fetchone()[0] is not None:
            cur.execute(f"ALTER DATABASE [{TEST_DATABASE}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            cur.execute(f"DROP DATABASE [{TEST_DATABASE}]")
        cur.execute(f"CREATE DATABASE [{TEST_DATABASE}]")
    finally:
        conn.close()
    print(f"Database {TEST_DATABASE} re-created (empty).")


def reset_mail() -> None:
    import shutil
    # only ever empty the two sub-folders of a folder that is inside the e2e runtime area or was named explicitly
    for sub in ("outbox", "inbox"):
        shutil.rmtree(MAIL_DIR / sub, ignore_errors=True)
        (MAIL_DIR / sub).mkdir(parents=True, exist_ok=True)
    print(f"Test mailbox emptied: {MAIL_DIR}")


def seed() -> None:
    from app.core.security import hash_password
    from app.repositories import stock_repository, user_repository, vendor_repository
    from scripts import seed_departments
    from scripts.stock_catalog import STOCK

    for username, role, label, email in ACCOUNTS:
        user_repository.upsert_user(username=username, password_hash=hash_password(PASSWORD), role=role,
                                    display_name=label, email=email)
        print(f"   {username:<11} {role}")
    sys.argv = ["seed_departments", "--password", PASSWORD]
    seed_departments.main()
    for name, reliability, email in VENDORS:
        vendor_repository.upsert_vendor(name, reliability, email)
        print(f"   supplier {name} <{email}>")
    for description, quantity in STOCK:
        stock_repository.upsert_stock(description, quantity)
    print(f"   stock: {len(STOCK)} item(s)")


def serve() -> None:
    import uvicorn
    reset_mail_if_missing()
    # The public /decide endpoint allows 40 calls per 10 minutes per address, which a full test run exceeds from one machine.
    # Relax it in THIS test process only (no product code changes); the limiter itself is covered by the backend unit tests.
    from app.api.routes import decisions
    from app.core.rate_limit import RateLimit
    decisions._limit = RateLimit(limit=100_000, window_seconds=600)
    uvicorn.run("app.main:app", host="127.0.0.1", port=API_PORT, log_level="info")


def reset_mail_if_missing() -> None:
    for sub in ("outbox", "inbox"):
        (MAIL_DIR / sub).mkdir(parents=True, exist_ok=True)


def main() -> int:
    commands = {"reset-db", "migrate", "seed", "reset-mail", "serve"}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    if API_PORT in (8000, 8001) or WEB_PORT in (5180, 5181):
        print("Refusing: those ports belong to the real servers.", file=sys.stderr)
        return 2
    apply_env()
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    command = sys.argv[1]
    if command == "reset-db":
        reset_db()
    elif command == "reset-mail":
        reset_mail()
    elif command == "migrate":
        from scripts import migrate
        return migrate.main()
    elif command == "seed":
        seed()
    else:
        serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
