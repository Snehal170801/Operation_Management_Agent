"""Tells you when the whole server is down. The app cannot report its own death, so this runs as a separate program.

    python -m scripts.watchdog                      # checks http://localhost:8000/health every 60 s
    python -m scripts.watchdog --url http://host:8000/health --to ops@company.com

It emails once when the server has failed 3 checks in a row, and once when it comes back. It needs the same SMTP_*
settings as the app (backend/.env). Recipients: --to (comma separated) or WATCHDOG_ALERT_TO in .env, or, if neither
is set, every active admin's email from the database (which works only while the database itself is up).
"""

import argparse
import os
import time
import urllib.request

FAILS_BEFORE_ALERT = 3


class Tracker:
    """Decides when to speak. Pure: it only sees "up or down" and returns what to announce."""

    def __init__(self, fails_before_alert: int = FAILS_BEFORE_ALERT) -> None:
        self.limit = fails_before_alert
        self.fails = 0
        self.down_since: float | None = None
        self.announced = False

    def step(self, up: bool, now: float) -> str | None:
        if up:
            recovered = self.announced
            self.fails, self.announced, self.down_since = 0, False, None
            return "recovered" if recovered else None
        self.fails += 1
        self.down_since = self.down_since or now
        if self.fails >= self.limit and not self.announced:
            self.announced = True
            return "down"
        return None


def is_up(url: str, timeout: float = 10) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as reply:  # noqa: S310 (a URL the operator chose)
            return 200 <= reply.status < 300
    except Exception:
        return False


def recipients(cli: str | None) -> list[str]:
    raw = cli or os.environ.get("WATCHDOG_ALERT_TO", "")
    found = [a.strip() for a in raw.split(",") if a.strip()]
    if found:
        return found
    try:
        from app.repositories import user_repository

        return [u.email for u in user_repository.find_active_users_with_permission("system:write") if u.email]
    except Exception:
        return []


def message(kind: str, url: str, since: float | None) -> tuple[str, str]:
    when = time.strftime("%d %b %H:%M", time.localtime(since)) if since else "just now"
    if kind == "recovered":
        return "Recovered: Operation Agents server is back", f"The server at {url} is answering again.\n\nIt was down since {when}.\n"
    return (
        "ALERT: Operation Agents server is DOWN",
        f"The server at {url} has stopped answering (since {when}).\n\nNothing is being followed up, escalated or "
        f"emailed while it is down.\nStart it again: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 (in the backend folder).\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000/health")
    parser.add_argument("--to", default=None)
    parser.add_argument("--every", type=int, default=60, help="seconds between checks")
    args = parser.parse_args()

    from app.clients import email_client  # the app's own mail sender, so it uses the same SMTP_* settings

    tracker = Tracker()
    print(f"Watching {args.url} every {args.every}s. Ctrl+C to stop.")
    while True:
        up = is_up(args.url)
        kind = tracker.step(up, time.time())
        print(time.strftime("%H:%M:%S"), "up" if up else f"DOWN ({tracker.fails})", f"-> {kind}" if kind else "")
        if kind:
            to = recipients(args.to)
            subject, body = message(kind, args.url, tracker.down_since)
            if not to:
                print("  nobody to tell: set --to or WATCHDOG_ALERT_TO")
            for address in to:
                try:
                    email_client.send_email(address, subject, body)
                except Exception as exc:
                    print(f"  could not email {address}: {exc}")
        time.sleep(args.every)


if __name__ == "__main__":
    main()
