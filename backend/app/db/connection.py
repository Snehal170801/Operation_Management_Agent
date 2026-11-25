import os

import pyodbc

from app.core.config import settings
from app.core.retry import retry

# Without timeouts a stuck database call hangs its request forever, and enough of those use up every
# worker thread until the whole API stops answering. Fail fast instead (seconds; 0 disables a limit).
LOGIN_TIMEOUT_SECONDS = int(os.environ.get("SQL_LOGIN_TIMEOUT", "10"))
QUERY_TIMEOUT_SECONDS = int(os.environ.get("SQL_QUERY_TIMEOUT", "30"))


# SQLSTATEs that mean "could not reach / talk to the server right now" (08xxx connection problems, HYT00/HYT01 timeouts).
# A wrong login or a missing driver (28000, IM002) is NOT passing, so it fails at once.
_PASSING = ("08", "HYT00", "HYT01", "01000", "HY000")


def is_connection_problem(exc: BaseException) -> bool:
    """True for a database error that is about reaching the server, not about the query or the login."""
    if not isinstance(exc, pyodbc.Error) or not exc.args:
        return False
    state = str(exc.args[0])
    if state.startswith(("28", "IM", "42")):
        return False
    text = " ".join(str(a) for a in exc.args).lower()
    return state.startswith(_PASSING) or any(w in text for w in ("communication link", "timeout expired", "connection is closed", "server not found", "shared memory", "tcp provider"))


def get_connection():
    conn_str = (
        f"DRIVER={settings.SQL_DRIVER};"
        f"SERVER={settings.SQL_SERVER};"
        f"DATABASE={settings.SQL_DATABASE};"
        f"Trusted_Connection={settings.SQL_TRUSTED_CONNECTION};"
    )
    # A brief network or server hiccup should not fail the person's request: two quick retries first.
    conn = retry(lambda: pyodbc.connect(conn_str, timeout=LOGIN_TIMEOUT_SECONDS), attempts=3, delay=0.3,
                 transient=is_connection_problem, what="Database connection")
    conn.timeout = QUERY_TIMEOUT_SECONDS
    return conn
