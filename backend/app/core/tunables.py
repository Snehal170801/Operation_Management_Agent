"""The settings an administrator may change from the Configure tab, without touching files or restarting.

A changed value is saved in dbo.SystemSettings (key `config.<NAME>`) and applied straight onto `settings`, which the
rest of the code reads each time it needs a value. The value from the environment file stays as the default, so
"Reset" simply goes back to it. Only the settings listed here can be changed this way; secrets and connections never are.
"""

from dataclasses import dataclass

from app.core.config import settings
from app.repositories import automation_repository

PREFIX = "config."


@dataclass(frozen=True)
class Tunable:
    key: str
    label: str
    help: str
    group: str
    kind: str  # "int" | "float" | "bool"
    unit: str = ""
    minimum: float = 0
    maximum: float = 1_000_000


GROUPS: tuple[tuple[str, str, str], ...] = (
    ("reminders", "Reminders & follow-ups", "How often the agents chase people, and how many times, before a person is told."),
    ("urgent", "Urgent requests", "Requests with a needed-by date are chased harder: less time to quote, sooner reminders and escalation."),
    ("approval", "Automatic approval", "When an order may go ahead on its own, and when a person must decide."),
    ("invoice", "Invoice checking", "How strictly an invoice is compared with its order."),
    ("requests", "Requests & stock", "Limits on new requests and when stock counts as low."),
    ("stuck", "Stuck requests", "A safety net: a request that sits at one step far too long is reported to the right department, then to the admin. 0 switches a limit off."),
    ("worker", "Background worker", "How often the agents look for work."),
    ("summary", "Daily summary", "One short e-mail each morning to each department, listing what is waiting for it."),
    ("calls", "Phone calls", "The 'check your email' call after an email goes to a supplier."),
    ("security", "Security", "Sign-in protection."),
)

CATALOG: tuple[Tunable, ...] = (
    Tunable("RFQ_DEADLINE_HOURS", "Time suppliers get to quote", "After this long with no quote at all, the request is marked stuck and the Vendor team is alerted.", "reminders", "int", "hours", 1, 720),
    Tunable("RFQ_REMINDER_HOURS", "Remind silent suppliers every", "A supplier who has not replied is reminded this often.", "reminders", "int", "hours", 1, 720),
    Tunable("RFQ_MAX_REMINDERS", "Most reminders to a supplier", "After this many reminders the system stops asking that supplier.", "reminders", "int", "times", 0, 20),
    Tunable("APPROVAL_REMINDER_HOURS", "Remind approvers every", "An order waiting for a decision re-notifies the approvers this often.", "reminders", "int", "hours", 1, 720),
    Tunable("APPROVAL_MAX_REMINDERS", "Most approval reminders", "After this many, only the escalation below remains.", "reminders", "int", "times", 0, 20),
    Tunable("PO_CONFIRM_HOURS", "Ask a supplier to confirm an order every", "After an order is emailed, a supplier who has not confirmed it is asked again this often.", "reminders", "float", "hours", 1, 720),
    Tunable("PO_CONFIRM_MAX_CHASES", "Most order-confirmation reminders", "After this many, the PO team is alerted.", "reminders", "int", "times", 0, 20),
    Tunable("DELIVERY_CHASE_INTERVAL_HOURS", "Chase a late delivery every", "Once an order is past its due date the supplier is chased this often.", "reminders", "int", "hours", 1, 720),
    Tunable("DELIVERY_MAX_CHASES", "Most delivery chases", "After this many, the Receiving team is alerted.", "reminders", "int", "times", 0, 20),
    Tunable("PDF_VISION_ENABLED", "Read scanned PDFs and photos of invoices", "When a document has no text (a scan or a photo), the AI looks at the page image. Switch off to ask the supplier for a text version instead.", "invoice", "bool"),
    Tunable("PDF_VISION_MAX_PAGES", "Pages of a scan the AI looks at", "Only the first pages of a scanned document are read. More pages cost more.", "invoice", "int", "pages", 1, 5),
    Tunable("INVOICE_CHASE_HOURS", "Chase a rejected invoice every", "After an invoice is rejected, the supplier is reminded to send a corrected one this often.", "reminders", "float", "hours", 1, 720),
    Tunable("INVOICE_MAX_CHASES", "Most invoice reminders", "After this many, Accounts is told.", "reminders", "int", "times", 0, 20),
    Tunable("ESCALATE_AFTER_HOURS", "Tell the admin if nobody acts after", "A problem nobody has handled for this long is escalated to the admin once. 0 switches escalation off.", "reminders", "float", "hours", 0, 720),

    Tunable("URGENT_WITHIN_DAYS", "A needed-by date within this many days is urgent", "A request needed this soon is treated as urgent even if nobody ticked the box.", "urgent", "int", "days", 0, 60),
    Tunable("URGENT_RFQ_DEADLINE_HOURS", "Urgent: time suppliers get to quote", "Never more than 40% of the time left before the needed-by date.", "urgent", "float", "hours", 1, 240),
    Tunable("URGENT_REMINDER_HOURS", "Urgent: remind silent suppliers every", "", "urgent", "float", "hours", 1, 240),
    Tunable("URGENT_APPROVAL_REMINDER_HOURS", "Urgent: remind approvers every", "", "urgent", "float", "hours", 1, 240),
    Tunable("URGENT_ESCALATE_HOURS", "Urgent: tell the admin if nobody acts after", "A stuck urgent request reaches the admin this soon.", "urgent", "float", "hours", 1, 240),
    Tunable("AUTO_APPROVE_MAX_AMOUNT", "Largest order approved automatically", "An order above this amount waits for a person. When a tax rate is set, the amount counts WITH tax.", "approval", "float", "₹", 0, 100_000_000),
    Tunable("AUTO_APPROVE_MIN_RELIABILITY", "Lowest supplier rating allowed", "A supplier rated below this (out of 5) needs a person's approval.", "approval", "float", "out of 5", 0, 5),
    Tunable("AUTO_APPROVE_MIN_QUOTES", "Fewest quotes needed", "With fewer quotes than this, a person must approve.", "approval", "int", "quotes", 1, 20),
    Tunable("AUTO_APPROVE_DAILY_LIMIT", "Most spent automatically per day", "Once today's automatic orders add up to this, a person decides the rest. Amounts count with tax when a tax rate is set.", "approval", "float", "₹", 0, 1_000_000_000),

    Tunable("EMAIL_APPROVE_ENABLED", "Approve or refuse from the email", "The approval email carries one-tap buttons. Switch off to make everyone use the app.", "approval", "bool"),
    Tunable("EMAIL_APPROVE_HOURS", "An email button works for", "After this long the link stops working and the approver uses the app.", "approval", "float", "hours", 1, 720),
    Tunable("EMAIL_APPROVE_MAX_AMOUNT", "Email buttons only for orders up to", "A larger order has no button: it must be decided in the app. 0 turns the buttons off. Amounts count with tax when a tax rate is set.", "approval", "float", "₹", 0, 100_000_000),
    Tunable("RESOURCE_MAX_ROUNDS", "Times a request may be sent back for new quotes", "After a rejection the approver can ask the suppliers again. This stops a request going round forever. 0 switches it off.", "approval", "int", "times", 0, 10),
    Tunable("PRICE_CHANGE_TOLERANCE_PCT", "A changed price counts as the same price within", "When a supplier restates the price after the order, a difference this small is ignored. A higher price beyond it goes to an approver.", "approval", "float", "%", 0, 50),
    Tunable("TAX_RATE_PCT", "Tax (GST) rate on orders", "When above 0, each order shows its tax lines and an invoice is also checked for tax (rate, amount, total). 0 means tax is not tracked. Matching only: nothing is paid.", "invoice", "float", "%", 0, 100),
    Tunable("TAX_INCLUDED_IN_QUOTES", "Supplier prices already include tax", "On: the quoted price is the total with tax. Off: tax is added on top of the quoted price.", "invoice", "bool"),
    Tunable("INVOICE_AMOUNT_TOLERANCE_PCT", "Invoice amount may differ by", "An invoice total within this percent of the order total still counts as matching.", "invoice", "float", "%", 0, 50),

    Tunable("MAX_REQUESTS_PER_USER_PER_DAY", "Requests one person may make per day", "Each request uses the AI, so this stops flooding.", "requests", "int", "requests", 1, 1000),
    Tunable("DUPLICATE_REQUEST_MINUTES", "Treat the same request as a double-click for", "An identical request from the same person within this time is ignored.", "requests", "int", "minutes", 0, 1440),
    Tunable("NEGOTIATE_ENABLED", "Ask the best supplier for a better price", "After the best quote is chosen, that supplier is asked once by e-mail for a better price. A lower reply is taken, anything else keeps the original quote. The approval rules still decide.", "requests", "bool"),
    Tunable("NEGOTIATE_WAIT_HOURS", "Wait for the better price", "How long the supplier has to answer before the original quote is used.", "requests", "float", "hours", 1, 168),
    Tunable("AUTO_REORDER_ENABLED", "Reorder low stock automatically", "When an item reaches its minimum level, a reorder up to its target is raised by itself (items with both levels set). An approver ALWAYS approves it, whatever the amount. Never twice while one is in progress.", "requests", "bool"),
    Tunable("AUTO_REORDER_MAX_PER_PASS", "Most automatic reorders at a time", "If many items are low at once, only this many reorders are raised per pass and the rest follow, so approvers are not flooded.", "requests", "int", "reorders", 1, 50),
    Tunable("AUTO_REORDER_COOLDOWN_HOURS", "Wait before reordering the same item again", "After an automatic reorder, the same item is not reordered automatically again for this long (so a refused or cancelled order does not come straight back). 0 means no wait.", "requests", "float", "hours", 0, 720),
    Tunable("LOW_STOCK_AT", "Show stock as low at", "Stock at or below this many is shown to Stores as running low.", "requests", "int", "items", 0, 100_000),
    Tunable("COMBINE_SUGGESTIONS", "Suggest combining requests for the same item", "When two people ask for the same item while suppliers are still being asked, the Vendor team is offered a single combined order.", "requests", "bool"),
    Tunable("COMBINE_WINDOW_HOURS", "Only compare requests started within", "The newer request is compared with older ones started this recently.", "requests", "float", "hours", 1, 720),
    Tunable("HANDLED_HOURS", "Keep finished work on My work for", "Each team sees what it handled in this time under \"Recently handled\".", "requests", "float", "hours", 1, 720),
    Tunable("HELD_CASE_GRACE_MINUTES", "Wait before picking up a held request", "A request that was held (for example while automation was paused) is picked up after this long.", "requests", "int", "minutes", 0, 1440),

    Tunable("STUCK_AUTOMATIC_HOURS", "A step that should be automatic is stuck after", "Steps the agents do by themselves (reading a request, choosing, placing the order). Longer than this means something broke.", "stuck", "float", "hours", 0, 720),
    Tunable("STUCK_PERSON_HOURS", "Waiting on a person is stuck after", "Approvals and failed steps a person must fix.", "stuck", "float", "hours", 0, 720),
    Tunable("STUCK_WAITING_HOURS", "Waiting on a supplier or delivery is stuck after", "Quotes, goods and invoices have their own reminders; this is the last safety net.", "stuck", "float", "hours", 0, 2000),
    Tunable("STUCK_ESCALATE_AFTER_HOURS", "Tell the admin if still stuck this long after the department was told", "0 means the admin is not told.", "stuck", "float", "hours", 0, 720),
    Tunable("STUCK_MAX_PER_TICK", "Most stuck-request notices per pass", "When many old requests are found at once, only this many are reported each pass and the rest follow, so nobody is flooded with email.", "stuck", "int", "notices", 1, 100),
    Tunable("LOOP_RESTARTS_PER_HOUR", "Restart a stuck background job up to", "When the worker or the instant mailbox watcher stops, the app restarts it by itself, at most this many times an hour. 0 switches it off. The admins are told.", "worker", "int", "times an hour", 0, 20),
    Tunable("WORKER_INTERVAL_SECONDS", "Agents look for work every", "Also how quickly time-based follow-ups are noticed. Replies in the mailbox are read instantly regardless.", "worker", "int", "seconds", 10, 3600),

    Tunable("DESK_SUMMARY_ENABLED", "E-mail each department its morning summary", "Each department with something waiting gets one short e-mail listing it (administrators are not included; they see everything in the app).", "summary", "bool"),
    Tunable("DESK_SUMMARY_HOUR", "Send it at", "Hour of the day, India time, 24-hour clock. If the server was off then, it is still sent within a few hours.", "summary", "int", "o'clock", 0, 23),
    Tunable("WEEKLY_SUMMARY_ENABLED", "E-mail the admins a weekly summary", "Once a week: requests, orders and spend, how much needed no person, what is stuck and what is waiting. Sent to the admins only.", "summary", "bool"),
    Tunable("WEEKLY_SUMMARY_DAY", "Weekly summary day", "0 = Monday, 1 = Tuesday ... 6 = Sunday.", "summary", "int", "day (0 = Monday)", 0, 6),
    Tunable("WEEKLY_SUMMARY_HOUR", "Weekly summary time", "Hour of the day, India time, 24-hour clock. If the server was off then, it is still sent within a day.", "summary", "int", "o'clock", 0, 23),
    Tunable("CALL_AFTER_EMAIL", "Ring suppliers after emailing them", "Needs a paid Twilio account. Off by default.", "calls", "bool"),
    Tunable("CALL_HOURS_START", "Only call from", "Hour of the day, India time, 24-hour clock.", "calls", "int", "o'clock", 0, 23),
    Tunable("CALL_HOURS_END", "Only call until", "Hour of the day, India time, 24-hour clock. Calls outside these hours are skipped.", "calls", "int", "o'clock", 1, 24),

    Tunable("MAX_FAILED_LOGINS", "Lock an account after wrong passwords", "Number of wrong passwords in a row before the account is locked.", "security", "int", "tries", 1, 50),
    Tunable("LOCKOUT_MINUTES", "A locked account stays locked for", "How long before the person can try again.", "security", "int", "minutes", 1, 1440),
    Tunable("ALLOW_OPEN_ACCOUNT", "Let the admin open department accounts", "The Accounts tab shortcut. Switch it off before real use.", "security", "bool"),
)

BY_KEY = {t.key: t for t in CATALOG}
# What the environment file gave, before any change made here.
DEFAULTS: dict[str, object] = {t.key: getattr(settings, t.key) for t in CATALOG}


class InvalidSetting(ValueError):
    pass


def _coerce(t: Tunable, raw) -> object:
    if t.kind == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        raise InvalidSetting(f"{t.label}: choose on or off.")
    try:
        if isinstance(raw, bool):
            raise ValueError
        number = float(raw)
    except (TypeError, ValueError):
        raise InvalidSetting(f"{t.label}: enter a number.") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise InvalidSetting(f"{t.label}: enter a number.")
    if t.kind == "int":
        if number != int(number):
            raise InvalidSetting(f"{t.label}: enter a whole number.")
        number = int(number)
    if number < t.minimum or number > t.maximum:
        unit = f" {t.unit}" if t.unit else ""
        raise InvalidSetting(f"{t.label}: must be between {t.minimum:g} and {t.maximum:g}{unit}.")
    return number


def _store(value) -> str:
    return ("1" if value else "0") if isinstance(value, bool) else repr(value)


def validate(changes: dict) -> dict[str, object]:
    """Every change checked (nothing is applied if one is wrong). Returns the cleaned values."""
    clean: dict[str, object] = {}
    for key, raw in changes.items():
        t = BY_KEY.get(key)
        if t is None:
            raise InvalidSetting(f"'{key}' is not a setting that can be changed here.")
        clean[key] = _coerce(t, raw)
    start = clean.get("CALL_HOURS_START", settings.CALL_HOURS_START)
    end = clean.get("CALL_HOURS_END", settings.CALL_HOURS_END)
    if start >= end:
        raise InvalidSetting("Phone calls: the 'from' hour must be earlier than the 'until' hour.")
    return clean


def current(key: str):
    return getattr(settings, key)


def refresh() -> None:
    """Take whatever is saved in the database (so every running copy of the app agrees). A bad or unknown row is ignored."""
    saved = {r.setting_key[len(PREFIX):]: r.setting_value for r in automation_repository.list_settings(PREFIX)}
    for t in CATALOG:
        value = DEFAULTS[t.key]
        if t.key in saved:
            try:
                value = _coerce(t, saved[t.key])
            except InvalidSetting:
                pass
        setattr(settings, t.key, value)


def save(changes: dict, by: str | None) -> dict[str, tuple[object, object]]:
    """Validate, save and apply. Returns {key: (old, new)} for what actually changed."""
    clean = validate(changes)
    changed: dict[str, tuple[object, object]] = {}
    for key, value in clean.items():
        old = current(key)
        if value == DEFAULTS[key]:
            # Always clear the saved row, even if this copy already shows the default (another copy may have saved one).
            automation_repository.delete_setting(PREFIX + key)
        elif value != old:
            automation_repository.set_setting(PREFIX + key, _store(value), by)
        if value == old:
            continue
        setattr(settings, key, value)
        changed[key] = (old, value)
    return changed


def reset(keys: list[str] | None, by: str | None) -> dict[str, tuple[object, object]]:
    """Back to the defaults, for the given settings or (None) all of them."""
    return save({k: DEFAULTS[k] for k in (keys or [t.key for t in CATALOG]) if k in BY_KEY}, by)
