from app.controllers import system_controller
from app.repositories import system_repository


def _health(monkeypatch, **settings):
    monkeypatch.setattr(system_repository, "get_db_overview", lambda: {
        "server_version": "x", "users": 1, "active_sessions": 0, "cases": 0, "open_cases": 0, "migrations_applied": 1})
    for key, value in settings.items():
        monkeypatch.setattr(system_controller.settings, key, value)
    return {c.name: c for c in system_controller.get_health().checks}


def test_unconfigured_email_is_a_visible_warning_not_a_silent_success(monkeypatch):
    checks = _health(monkeypatch, SMTP_HOST="", SMTP_USER="", SMTP_FROM="", IMAP_HOST="", IMAP_USER="")
    assert checks["Outgoing email"].status == "warning" and "NOT sent" in checks["Outgoing email"].detail
    assert checks["Mailbox reader"].status == "warning"


def test_configured_email_reports_ok(monkeypatch):
    checks = _health(monkeypatch, SMTP_HOST="smtp.gmail.com", SMTP_FROM="a@b.co", IMAP_HOST="imap.gmail.com", IMAP_USER="a@b.co")
    assert checks["Outgoing email"].status == "ok" and "smtp.gmail.com" in checks["Outgoing email"].detail
    assert checks["Mailbox reader"].status == "ok"
