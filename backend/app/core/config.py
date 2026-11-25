import os
from dotenv import load_dotenv

load_dotenv()


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    # Comma-separated list of allowed browser origins. Default is the Vite dev server.
    CORS_ORIGINS = _csv(os.environ.get("CORS_ORIGINS", "http://localhost:5180"))
    # In development, also accept the frontend opened by this machine's LAN address
    # (http://192.168.x.x:5180, http://10.x.x.x:5180). Never enabled outside development.
    CORS_ORIGIN_REGEX = os.environ.get(
        "CORS_ORIGIN_REGEX",
        r"^http://(127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}):5180$"
        if ENVIRONMENT == "development"
        else "",
    )

    # Approval policy: a vendor selection runs fully automatically unless one of
    # these limits is breached, in which case a human must approve it.
    # A rejected invoice: remind the supplier every INVOICE_CHASE_HOURS, up to INVOICE_MAX_CHASES times, then tell Accounts.
    INVOICE_CHASE_HOURS = float(os.environ.get("INVOICE_CHASE_HOURS", "24"))
    INVOICE_MAX_CHASES = int(os.environ.get("INVOICE_MAX_CHASES", "2"))
    # A problem that waits longer than this many hours is escalated to the admin (0 switches escalation off).
    ESCALATE_AFTER_HOURS = float(os.environ.get("ESCALATE_AFTER_HOURS", "24"))
    # "Stuck too long" sweep (core/stuck_policy.py): how long a case may sit quiet at a stage before the right department is told.
    STUCK_AUTOMATIC_HOURS = float(os.environ.get("STUCK_AUTOMATIC_HOURS", "2"))      # steps that should happen by themselves
    STUCK_PERSON_HOURS = float(os.environ.get("STUCK_PERSON_HOURS", "48"))           # waiting on a person
    STUCK_WAITING_HOURS = float(os.environ.get("STUCK_WAITING_HOURS", "168"))        # waiting on a supplier / delivery / invoice (7 days)
    STUCK_ESCALATE_AFTER_HOURS = float(os.environ.get("STUCK_ESCALATE_AFTER_HOURS", "24"))   # after the department was told, then the admin
    STUCK_MAX_PER_TICK = int(os.environ.get("STUCK_MAX_PER_TICK", "5"))                  # at most this many notices per worker pass; the rest follow on later passes
    # An administrator may open a department's account from the Accounts tab without its password (a shortcut for
    # testing and support). Every use is written to the audit log. Switch it off with ALLOW_OPEN_ACCOUNT=false.
    ALLOW_OPEN_ACCOUNT = os.environ.get("ALLOW_OPEN_ACCOUNT", "true").lower() == "true"
    OPEN_ACCOUNT_MINUTES = int(os.environ.get("OPEN_ACCOUNT_MINUTES", "60"))
    # My work keeps what a team finished for this many hours, under "Recently handled".
    HANDLED_HOURS = float(os.environ.get("HANDLED_HOURS", "24"))
    # After a rejection the approver may send the request back out for new quotes, at most this many times per request.
    RESOURCE_MAX_ROUNDS = int(os.environ.get("RESOURCE_MAX_ROUNDS", "2"))
    # An emailed purchase order the supplier has not confirmed: ask again every PO_CONFIRM_HOURS, up to PO_CONFIRM_MAX_CHASES times, then tell the PO team.
    PO_CONFIRM_HOURS = float(os.environ.get("PO_CONFIRM_HOURS", "24"))
    PO_CONFIRM_MAX_CHASES = int(os.environ.get("PO_CONFIRM_MAX_CHASES", "2"))
    # Urgent requests ("needed by Friday"): less time to quote, sooner reminders, sooner escalation.
    URGENT_WITHIN_DAYS = int(os.environ.get("URGENT_WITHIN_DAYS", "3"))          # a needed-by date this close makes a request urgent
    URGENT_RFQ_DEADLINE_HOURS = float(os.environ.get("URGENT_RFQ_DEADLINE_HOURS", "12"))
    URGENT_REMINDER_HOURS = float(os.environ.get("URGENT_REMINDER_HOURS", "4"))
    URGENT_APPROVAL_REMINDER_HOURS = float(os.environ.get("URGENT_APPROVAL_REMINDER_HOURS", "4"))
    URGENT_ESCALATE_HOURS = float(os.environ.get("URGENT_ESCALATE_HOURS", "4"))
    # A supplier asking for a different price after the order: within this percent it is the same price; above it a person decides.
    PRICE_CHANGE_TOLERANCE_PCT = float(os.environ.get("PRICE_CHANGE_TOLERANCE_PCT", "2"))
    # Two requests for the same item: suggest combining them when the newer one starts within this many hours of the older.
    # A scanned PDF or a photo of an invoice has no text to read, so the AI looks at the page image instead. A few pages at most (cost).
    PDF_VISION_ENABLED = os.environ.get("PDF_VISION_ENABLED", "true").lower() == "true"
    PDF_VISION_MAX_PAGES = int(os.environ.get("PDF_VISION_MAX_PAGES", "2"))
    COMBINE_SUGGESTIONS = os.environ.get("COMBINE_SUGGESTIONS", "true").lower() == "true"
    COMBINE_WINDOW_HOURS = float(os.environ.get("COMBINE_WINDOW_HOURS", "72"))
    # Deciding an approval straight from the email (Approve / Refuse buttons). The link works once, for one person, and expires.
    # Orders above EMAIL_APPROVE_MAX_AMOUNT are never offered a link: they are decided in the app.
    EMAIL_APPROVE_ENABLED = os.environ.get("EMAIL_APPROVE_ENABLED", "true").lower() == "true"
    EMAIL_APPROVE_HOURS = float(os.environ.get("EMAIL_APPROVE_HOURS", "48"))
    EMAIL_APPROVE_MAX_AMOUNT = float(os.environ.get("EMAIL_APPROVE_MAX_AMOUNT", "100000"))
    # Stock at or below this many is shown to Stores as running low.
    LOW_STOCK_AT = int(os.environ.get("LOW_STOCK_AT", "5"))
    # Negotiation: after the best quote is chosen, that supplier is asked ONCE for a better price (core/negotiation.py). Off until switched on.
    NEGOTIATE_ENABLED = os.environ.get("NEGOTIATE_ENABLED", "false").lower() == "true"
    NEGOTIATE_WAIT_HOURS = float(os.environ.get("NEGOTIATE_WAIT_HOURS", "24"))
    # Automatic reorder: when an item reaches its minimum a reorder is raised by itself. An approver ALWAYS approves it. Off until switched on.
    AUTO_REORDER_ENABLED = os.environ.get("AUTO_REORDER_ENABLED", "false").lower() == "true"
    AUTO_REORDER_MAX_PER_PASS = int(os.environ.get("AUTO_REORDER_MAX_PER_PASS", "3"))              # at most this many new reorders per worker pass
    AUTO_REORDER_COOLDOWN_HOURS = float(os.environ.get("AUTO_REORDER_COOLDOWN_HOURS", "24"))     # an item is not automatically reordered again within this time
    AUTO_APPROVE_MAX_AMOUNT = float(os.environ.get("AUTO_APPROVE_MAX_AMOUNT", "50000"))
    AUTO_APPROVE_MIN_RELIABILITY = float(os.environ.get("AUTO_APPROVE_MIN_RELIABILITY", "4.0"))
    AUTO_APPROVE_MIN_QUOTES = int(os.environ.get("AUTO_APPROVE_MIN_QUOTES", "2"))

    # Notifications to managers/admins (who have an email on their user record).
    # Pending approvals are re-sent every APPROVAL_REMINDER_HOURS, up to APPROVAL_MAX_REMINDERS times.
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5180").rstrip("/")

    # Demo phone calls (Exotel). The dashboard shows these under Settings -> API Settings.
    EXOTEL_ACCOUNT_SID = os.environ.get("EXOTEL_ACCOUNT_SID", "")
    EXOTEL_API_KEY = os.environ.get("EXOTEL_API_KEY", "")
    EXOTEL_API_TOKEN = os.environ.get("EXOTEL_API_TOKEN", "")
    # Your ExoPhone (the number calls appear to come from), digits as shown in the Exotel dashboard.
    EXOTEL_FROM_NUMBER = os.environ.get("EXOTEL_FROM_NUMBER", "")
    # The call flow (app) to run when the person answers. Use EXOTEL_CONNECT_TO instead to dial a second number.
    EXOTEL_APP_ID = os.environ.get("EXOTEL_APP_ID", "")
    EXOTEL_CONNECT_TO = os.environ.get("EXOTEL_CONNECT_TO", "")
    # api.in.exotel.com (Mumbai) for Indian accounts, api.exotel.com (Singapore) otherwise.
    EXOTEL_HOST = os.environ.get("EXOTEL_HOST", "api.in.exotel.com")
    # Longest the call may last, in seconds, once it is connected (Exotel's TimeLimit). 0 = no limit.
    # A few seconds means: ring, and hang up soon after the person picks up.
    EXOTEL_TIME_LIMIT = int(os.environ.get("EXOTEL_TIME_LIMIT", "0"))
    # Demo phone calls through Twilio (alternative to Exotel). The SID and token are on the Twilio Console home page.
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    # A Twilio number you own, in +country-code form. A free trial can only ring numbers verified in the console.
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
    # Spoken when they answer, before the call ends. Empty = hang up the moment they pick up.
    TWILIO_ANSWER_MESSAGE = os.environ.get("TWILIO_ANSWER_MESSAGE", "")
    # What Twilio runs when they answer. A free trial only allows Twilio-hosted templates (not inline TwiML), so this
    # defaults to the template used by the Twilio console's own "Try out Voice" page. Set it to "" on a paid account
    # to use TWILIO_ANSWER_MESSAGE / hang-up-on-answer instead.
    TWILIO_ANSWER_URL = os.environ.get("TWILIO_ANSWER_URL", "https://webhooks.twilio.com/v1/Voice/Template/voice_auto_response")
    # "twilio" or "exotel". Empty = Twilio if it is fully set up, otherwise Exotel.
    CALL_PROVIDER = os.environ.get("CALL_PROVIDER", "").strip().lower()
    # "Check your email" calls: after the system emails a vendor, ring them and say so in their language.
    # Needs Twilio with TWILIO_ANSWER_URL empty (a paid account), because the spoken text is custom. Off by default.
    CALL_AFTER_EMAIL = os.environ.get("CALL_AFTER_EMAIL", "false").lower() == "true"
    CALL_COMPANY_NAME = os.environ.get("CALL_COMPANY_NAME", "Cognexa")
    # Printed at the top of purchase orders and approval summaries. COMPANY_ADDRESS lines are separated by "|".
    COMPANY_NAME = os.environ.get("COMPANY_NAME", "Cognexa")
    COMPANY_ADDRESS = os.environ.get("COMPANY_ADDRESS", "")
    # Only ring during these hours (India time, 24h clock). Outside them the call is skipped, not queued.
    CALL_HOURS_START = int(os.environ.get("CALL_HOURS_START", "9"))
    CALL_HOURS_END = int(os.environ.get("CALL_HOURS_END", "19"))
    # Twilio voices per language. Marathi is only offered by Twilio through Google voices.
    CALL_VOICE_HI = os.environ.get("CALL_VOICE_HI", "Google.hi-IN-Chirp3-HD-Aoede")
    CALL_VOICE_MR = os.environ.get("CALL_VOICE_MR", "Google.mr-IN-Chirp3-HD-Aoede")
    CALL_VOICE_EN = os.environ.get("CALL_VOICE_EN", "Polly.Aditi")
    # Optional safety net: comma-separated numbers the app may ring. Empty = any.
    CALL_ALLOWED_NUMBERS = _csv(os.environ.get("CALL_ALLOWED_NUMBERS", ""))
    APPROVAL_REMINDER_HOURS = int(os.environ.get("APPROVAL_REMINDER_HOURS", "24"))
    APPROVAL_MAX_REMINDERS = int(os.environ.get("APPROVAL_MAX_REMINDERS", "3"))

    # An invoice total may differ from the purchase order total by up to this percent (rounding) and still match.
    INVOICE_AMOUNT_TOLERANCE_PCT = float(os.environ.get("INVOICE_AMOUNT_TOLERANCE_PCT", "1.0"))
    # Tax (GST) on orders and invoices, for matching only (core/tax.py). 0 = tax is not modelled and nothing changes.
    TAX_RATE_PCT = float(os.environ.get("TAX_RATE_PCT", "0"))
    TAX_INCLUDED_IN_QUOTES = os.environ.get("TAX_INCLUDED_IN_QUOTES", "false").lower() == "true"     # suppliers' prices already contain the tax

    # Automatic approvals stop (a person decides) once today's auto-approved orders add up to this much.
    AUTO_APPROVE_DAILY_LIMIT = float(os.environ.get("AUTO_APPROVE_DAILY_LIMIT", "200000"))

    # An identical request from the same person within this many minutes is treated as a double-click.
    DUPLICATE_REQUEST_MINUTES = int(os.environ.get("DUPLICATE_REQUEST_MINUTES", "10"))

    # Held cases are only picked up by the worker once they have sat untouched this long
    # (so it never races a request that is still being processed).
    HELD_CASE_GRACE_MINUTES = int(os.environ.get("HELD_CASE_GRACE_MINUTES", "5"))

    # Requesters (role `user`) can't flood the system: each request costs an AI call.
    MAX_REQUESTS_PER_USER_PER_DAY = int(os.environ.get("MAX_REQUESTS_PER_USER_PER_DAY", "20"))

    # Delivery tracking: once a PO is past its expected date the vendor is chased every
    # DELIVERY_CHASE_INTERVAL_HOURS, up to DELIVERY_MAX_CHASES times; if still undelivered a
    # human is alerted.
    DELIVERY_CHASE_INTERVAL_HOURS = int(os.environ.get("DELIVERY_CHASE_INTERVAL_HOURS", "24"))
    DELIVERY_MAX_CHASES = int(os.environ.get("DELIVERY_MAX_CHASES", "2"))

    # Automatic sourcing: how long vendors get to quote, how often silent ones are
    # chased, and how often the background worker checks open cases.
    RFQ_DEADLINE_HOURS = int(os.environ.get("RFQ_DEADLINE_HOURS", "48"))
    RFQ_REMINDER_HOURS = int(os.environ.get("RFQ_REMINDER_HOURS", "24"))
    RFQ_MAX_REMINDERS = int(os.environ.get("RFQ_MAX_REMINDERS", "2"))
    WORKER_ENABLED = os.environ.get("WORKER_ENABLED", "true").lower() == "true"
    WORKER_INTERVAL_SECONDS = int(os.environ.get("WORKER_INTERVAL_SECONDS", "60"))
    # A background loop that has gone quiet is restarted by the app itself, at most this many times an hour (0 = never; the admins are told either way).
    LOOP_RESTARTS_PER_HOUR = int(os.environ.get("LOOP_RESTARTS_PER_HOUR", "3"))
    # One short e-mail per department each morning listing what is waiting for it (on by default; an administrator can switch it off).
    DESK_SUMMARY_ENABLED = os.environ.get("DESK_SUMMARY_ENABLED", "true").lower() == "true"
    DESK_SUMMARY_HOUR = int(os.environ.get("DESK_SUMMARY_HOUR", "9"))      # India time, 24-hour clock
    # One e-mail a week to the admins: what the system did and what is waiting (on by default). Day: 0 = Monday ... 6 = Sunday.
    WEEKLY_SUMMARY_ENABLED = os.environ.get("WEEKLY_SUMMARY_ENABLED", "true").lower() == "true"
    WEEKLY_SUMMARY_DAY = int(os.environ.get("WEEKLY_SUMMARY_DAY", "0"))
    WEEKLY_SUMMARY_HOUR = int(os.environ.get("WEEKLY_SUMMARY_HOUR", "9"))

    # Outbound email to vendors. With no SMTP_HOST set, emails are only logged (dry run).
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "")

    # Inbound mailbox where vendors reply. Use a DEDICATED mailbox: replies are marked read
    # once processed. With no IMAP_HOST the worker does not read mail (quotes stay manual).
    IMAP_HOST = os.environ.get("IMAP_HOST", "")
    IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
    IMAP_USER = os.environ.get("IMAP_USER", "")
    IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "")
    IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")

    # Auth. Access tokens are short-lived JWTs held in browser memory; the refresh
    # token is an opaque random value in an httpOnly cookie, stored hashed in the DB.
    JWT_SECRET = os.environ["JWT_SECRET"]
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_MINUTES = int(os.environ.get("ACCESS_TOKEN_MINUTES", "15"))
    REFRESH_TOKEN_DAYS = int(os.environ.get("REFRESH_TOKEN_DAYS", "7"))
    REFRESH_TOKEN_REMEMBER_DAYS = int(os.environ.get("REFRESH_TOKEN_REMEMBER_DAYS", "30"))
    COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

    # Password reset by emailed one-time code.
    OTP_TTL_MINUTES = int(os.environ.get("OTP_TTL_MINUTES", "10"))
    OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
    OTP_RESEND_SECONDS = int(os.environ.get("OTP_RESEND_SECONDS", "60"))
    OTP_MAX_PER_HOUR = int(os.environ.get("OTP_MAX_PER_HOUR", "5"))
    MAX_FAILED_LOGINS = int(os.environ.get("MAX_FAILED_LOGINS", "5"))
    LOCKOUT_MINUTES = int(os.environ.get("LOCKOUT_MINUTES", "15"))

    SQL_SERVER = os.environ["SQL_SERVER"]
    SQL_DATABASE = os.environ["SQL_DATABASE"]
    SQL_DRIVER = os.environ["SQL_DRIVER"]
    SQL_TRUSTED_CONNECTION = os.environ["SQL_TRUSTED_CONNECTION"]
    AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    AZURE_OPENAI_DEPLOYMENT_NAME = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
    AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")


    # ---- test-only switches (see core/test_switches.py: the app refuses to start unless it is a *_test database, not production)
    # A folder used instead of SMTP/IMAP: sent emails are written to <dir>/outbox, supplier replies are dropped into <dir>/inbox.
    TEST_MAIL_DIR = os.environ.get("TEST_MAIL_DIR", "").strip()
    # Deterministic stand-in for Azure OpenAI (no network, no cost, same answer every time).
    TEST_AI_STUB = os.environ.get("TEST_AI_STUB", "false").strip().lower() == "true"


settings = Settings()

from app.core import test_switches  # noqa: E402

_unsafe = test_switches.problems(settings.ENVIRONMENT, settings.SQL_DATABASE, settings.TEST_MAIL_DIR, settings.TEST_AI_STUB, settings.CALL_AFTER_EMAIL)
if _unsafe:
    raise RuntimeError("Refusing to start with TEST_MAIL_DIR / TEST_AI_STUB set: " + "; ".join(_unsafe))
