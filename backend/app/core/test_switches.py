"""Test-only switches: a folder that stands in for the mailbox, and a stand-in for the AI. They exist so automated end-to-end tests can
run without real email, real AI, or real data. They are dangerous next to real data, so the app refuses to start unless every one of
these holds. Pure function: no imports from the app, so config.py can call it while loading."""


def problems(environment: str, database: str, mail_dir: str, ai_stub: bool, calls_on: bool) -> list[str]:
    """Why the test switches cannot be used with these settings (an empty list means they are fine, or not in use)."""
    if not (mail_dir or ai_stub):
        return []
    found = []
    if (environment or "").strip().lower() == "production":
        found.append("ENVIRONMENT is production")
    if not (database or "").strip().lower().endswith("_test"):
        found.append(f"SQL_DATABASE is {database!r}; a database used with test switches must be named ending in _test")
    if calls_on:
        found.append("CALL_AFTER_EMAIL is on (a test run must never phone anyone)")
    return found
