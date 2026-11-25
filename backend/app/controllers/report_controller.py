from datetime import datetime, timedelta, timezone

from app.agents import operations_agent
from app.core.reports import REPORT_EVENT_TYPES, build_report
from app.models.report_schemas import Report
from app.repositories import report_repository

MAX_DAYS = 3650


def _plain(row, *fields) -> dict:
    return {f: (str(getattr(row, f)) if f in ("case_id", "vendor_id") else getattr(row, f)) for f in fields}


def get_report(days: int) -> Report:
    """The report for requests started in the last `days` days (0 = everything so far)."""
    days = max(0, min(int(days), MAX_DAYS))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since = now - timedelta(days=days) if days else None

    cases = [_plain(r, "case_id", "case_number", "stage", "status", "created_at", "updated_at") for r in report_repository.cases_since(since)]
    ids = {c["case_id"].lower() for c in cases}
    # A request started in the period has every one of its events at or after the start of the period.
    events = [e for e in operations_agent.get_events_of_types(REPORT_EVENT_TYPES, since) if e["case_id"].lower() in ids]
    rfqs = [_plain(r, "case_id", "vendor_id", "vendor_name", "sent_at", "replied_at", "status") for r in report_repository.rfqs_since(since)]
    pos = [_plain(r, "case_id", "vendor_id", "vendor_name", "total_amount", "created_at", "sent_at", "status", "expected_delivery_date",
                  "delivered_at", "delivery_status", "acknowledged_at") for r in report_repository.purchase_orders_since(since)]
    invoices = [_plain(r, "case_id", "vendor_id", "status") for r in report_repository.invoices_since(since)]
    return Report(**build_report(cases, events, rfqs, pos, invoices, now, days))
