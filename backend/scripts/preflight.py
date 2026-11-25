"""Check that everything the automatic flow depends on is in place, before running a pilot.

    python -m scripts.preflight             # configuration and connections (no AI call, no email sent)
    python -m scripts.preflight --live-ai   # also makes one tiny Azure OpenAI call

Prints OK / WARN / FAIL for each check and exits 1 if anything FAILED. A WARN means the system will
run but part of the automation will not work (e.g. emails are only logged until SMTP is set).
"""

import argparse
import imaplib
import smtplib
import sys
from pathlib import Path

from app.core.config import settings
from app.db.connection import get_connection

OK, WARN, FAIL = "OK", "WARN", "FAIL"

REQUIRED_TABLES = (
    "Cases", "CaseEvents", "PurchaseRequests", "Stock", "Vendors", "VendorQuotes", "Approvals", "Rfqs",
    "PurchaseOrders", "Invoices", "Users", "Roles", "RolePermissions", "SystemSettings", "WorkerLeases",
)
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _scalar(cur, sql: str, *params):
    cur.execute(sql, *params)
    return cur.fetchone()[0]


def check_database() -> list[tuple[str, str, str]]:
    results = []
    try:
        conn = get_connection()
    except Exception as exc:
        return [(FAIL, "Database", f"cannot connect to {settings.SQL_DATABASE} on {settings.SQL_SERVER}: {exc}")]
    try:
        cur = conn.cursor()
        results.append((OK, "Database", f"connected to {settings.SQL_DATABASE}"))

        existing = {r.name for r in cur.execute("SELECT name FROM sys.tables").fetchall()}
        missing = [t for t in REQUIRED_TABLES if t not in existing]
        results.append((FAIL, "Tables", f"missing {', '.join(missing)} - run: python -m scripts.migrate")
                       if missing else (OK, "Tables", "all required tables exist"))

        if "SchemaMigrations" in existing:
            applied = _scalar(cur, "SELECT COUNT(*) FROM dbo.SchemaMigrations")
            total = len(list(MIGRATIONS_DIR.glob("*.sql")))
            results.append((OK, "Migrations", f"{applied}/{total} applied") if applied >= total
                           else (FAIL, "Migrations", f"{applied}/{total} applied - run: python -m scripts.migrate"))

        if not missing:
            if not _scalar(cur, "SELECT COUNT(*) FROM dbo.Roles WHERE name = 'user'"):
                results.append((FAIL, "Roles", "the 'user' role is missing - run the migrations"))
            admins = _scalar(cur, "SELECT COUNT(*) FROM dbo.Users WHERE role = 'admin' AND is_active = 1")
            results.append((OK, "Admin account", f"{admins} active") if admins
                           else (FAIL, "Admin account", "none - run scripts.seed_pilot or scripts.create_user"))
            notify = _scalar(cur, "SELECT COUNT(*) FROM dbo.Users WHERE role IN ('manager','admin') "
                                  "AND is_active = 1 AND email IS NOT NULL")
            results.append((OK, "Alert recipients", f"{notify} manager/admin with an email") if notify
                           else (WARN, "Alert recipients", "no manager/admin has an email: nobody will be alerted"))
            vendors = _scalar(cur, "SELECT COUNT(*) FROM dbo.Vendors")
            reachable = _scalar(cur, "SELECT COUNT(*) FROM dbo.Vendors WHERE email IS NOT NULL")
            results.append((OK, "Suppliers", f"{reachable} of {vendors} have an email") if reachable
                           else (FAIL, "Suppliers", "none has an email, so quote requests cannot be sent"))
            stock = _scalar(cur, "SELECT COUNT(*) FROM dbo.Stock")
            results.append((OK, "Stock", f"{stock} item(s)") if stock
                           else (WARN, "Stock", "empty: every request will go out to suppliers"))
            paused = cur.execute(
                "SELECT setting_value FROM dbo.SystemSettings WHERE setting_key = 'automation_paused'").fetchone()
            results.append((WARN, "Automation", "PAUSED - the agents are idle until resumed in Settings")
                           if paused and paused[0] == "1" else (OK, "Automation", "running"))
    except Exception as exc:
        results.append((FAIL, "Database", f"check failed: {exc}"))
    finally:
        conn.close()
    return results


def check_ai(live: bool) -> tuple[str, str, str]:
    if not (settings.AZURE_OPENAI_API_KEY and settings.AZURE_OPENAI_ENDPOINT):
        return FAIL, "Azure OpenAI", "AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT not set"
    if not live:
        return OK, "Azure OpenAI", f"configured ({settings.AZURE_OPENAI_DEPLOYMENT_NAME}); use --live-ai to test a call"
    try:
        from app.clients import azure_openai_client
        answer = azure_openai_client.ask_json('Reply with the JSON object {"ok": true}.', "ping")
        return (OK, "Azure OpenAI", "live call succeeded") if answer.get("ok") else \
               (WARN, "Azure OpenAI", f"call worked but gave an unexpected answer: {answer}")
    except Exception as exc:
        return FAIL, "Azure OpenAI", f"live call failed: {exc}"


def check_smtp() -> tuple[str, str, str]:
    if not settings.SMTP_HOST:
        return WARN, "Outgoing email", "SMTP_HOST not set: emails are only written to the log (dry run)"
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        return OK, "Outgoing email", f"logged in to {settings.SMTP_HOST}"
    except Exception as exc:
        return FAIL, "Outgoing email", f"cannot sign in to {settings.SMTP_HOST}: {exc}"


def check_imap() -> tuple[str, str, str]:
    if not settings.IMAP_HOST:
        return WARN, "Mailbox reader", "IMAP_HOST not set: supplier replies and invoices must be entered by hand"
    try:
        with imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT) as imap:
            imap.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
            status, _ = imap.select(settings.IMAP_FOLDER, readonly=True)
        return (OK, "Mailbox reader", f"signed in, folder {settings.IMAP_FOLDER} readable") if status == "OK" \
            else (FAIL, "Mailbox reader", f"folder {settings.IMAP_FOLDER} not found")
    except Exception as exc:
        return FAIL, "Mailbox reader", f"cannot sign in to {settings.IMAP_HOST}: {exc}"


def check_settings() -> list[tuple[str, str, str]]:
    results = []
    results.append((OK, "Background worker", f"on, every {settings.WORKER_INTERVAL_SECONDS}s")
                   if settings.WORKER_ENABLED else
                   (WARN, "Background worker", "WORKER_ENABLED=false: nothing will advance on its own"))
    if settings.ENVIRONMENT == "production" and not settings.COOKIE_SECURE:
        results.append((WARN, "Cookies", "COOKIE_SECURE is off in production"))
    if "localhost" in settings.APP_BASE_URL:
        results.append((WARN, "App link", f"APP_BASE_URL is {settings.APP_BASE_URL}: emailed links only work on this machine"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live-ai", action="store_true", help="also make one small Azure OpenAI call")
    args = parser.parse_args()

    results = check_database() + [check_ai(args.live_ai), check_smtp(), check_imap()] + check_settings()
    width = max(len(name) for _, name, _ in results)
    for status, name, detail in results:
        print(f"[{status:<4}] {name:<{width}}  {detail}")

    failed = sum(1 for s, _, _ in results if s == FAIL)
    warned = sum(1 for s, _, _ in results if s == WARN)
    print(f"\n{failed} failed, {warned} warning(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
