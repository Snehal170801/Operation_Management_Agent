import os

# Settings read required env vars at import time; give them dummies so tests need no .env or database.
for key, value in {
    "SQL_SERVER": "test",
    "SQL_DATABASE": "test",
    "SQL_DRIVER": "test",
    "SQL_TRUSTED_CONNECTION": "yes",
    "JWT_SECRET": "test-secret-test-secret-test-secret-123456",
    # The Azure client is built when the app is imported. Tests stub every AI call, so any value will do; without one a clean
    # checkout (no backend/.env) failed at import with "Missing credentials".
    "AZURE_OPENAI_API_KEY": "test-key",
    "AZURE_OPENAI_ENDPOINT": "https://example.invalid",
}.items():
    os.environ[key] = value


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _safety_controls_default_off(monkeypatch):
    """Tests run with no database. By default: automation is running, this process holds the
    worker lease, nothing has been spent today and no request is a duplicate. Individual tests
    override these to exercise the controls."""
    from app.agents import operations_agent
    from app.core import automation
    from app.repositories import purchase_order_repository

    monkeypatch.setattr(automation, "is_paused", lambda: False)
    monkeypatch.setattr(automation, "acquire_worker_lease", lambda ttl: True)
    monkeypatch.setattr(purchase_order_repository, "sum_auto_approved_since", lambda since: 0.0)
    monkeypatch.setattr(operations_agent, "find_recent_duplicate", lambda requester, text, minutes: None)


@pytest.fixture(autouse=True)
def _no_database_for_events(monkeypatch):
    """Case events (including the live step signals) are written to the database. Tests have none, so by
    default writing an event is a no-op; tests that care (fake_world, or ones that patch it) replace this."""
    from app.repositories import case_repository

    monkeypatch.setattr(case_repository, "insert_event", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_saved_configuration(monkeypatch):
    """Nothing is saved in a database during tests, and a test that changes a setting leaves the defaults behind."""
    from app.core import tunables
    from app.core.config import settings
    from app.repositories import automation_repository

    monkeypatch.setattr(automation_repository, "list_settings", lambda prefix: [])
    for key, value in tunables.DEFAULTS.items():
        monkeypatch.setattr(settings, key, value)


@pytest.fixture(autouse=True)
def _no_database_for_cross_case_events(monkeypatch):
    """Queues that look across cases (disputes, recently handled) read events from the database; tests have none."""
    from app.agents import operations_agent

    monkeypatch.setattr(operations_agent, "get_events_of_types", lambda types, since=None: [])
    from app.repositories import case_repository

    monkeypatch.setattr(case_repository, "find_events_by_case_id", lambda case_id: [])      # (a test that has a case replaces this)


@pytest.fixture(autouse=True)
def _no_database_for_goods_issues(monkeypatch):
    """No goods problems are recorded unless a test (or the fake world) says so."""
    from app.repositories import goods_issue_repository

    monkeypatch.setattr(goods_issue_repository, "find_by_case", lambda case_id: [])
    monkeypatch.setattr(goods_issue_repository, "find_open", lambda: [])
