from datetime import datetime, timezone

from app.agents import invoice_agent, operations_agent, purchase_order_agent
from app.controllers import stock_controller
from app.core import audit, case_access, exports
from app.models.auth_schemas import CurrentUser


def _case_numbers() -> dict[str, str]:
    return {c["case_id"].lower(): c["case_number"] for c in operations_agent.get_all_cases(None)}


def export(kind: str, user: CurrentUser, fmt: str = "csv") -> tuple[bytes, str]:
    """The CSV and its file name. A requester's case export holds only their own cases (the same filter as the list); the other exports
    are staff-only and checked by the route. Every export is written to the audit log."""
    if kind == "cases":
        rows = exports.case_rows(operations_agent.get_all_cases(case_access.requester_filter(user)))
    elif kind == "purchase-orders":
        rows = exports.purchase_order_rows(purchase_order_agent.list_purchase_orders(), _case_numbers())
    elif kind == "invoices":
        rows = exports.invoice_rows(invoice_agent.list_invoices(), _case_numbers())
    elif kind == "stock":
        rows = exports.stock_rows(stock_controller.get_all_stock())
    else:
        raise ValueError(kind)
    audit.record(f"export.{kind}", actor_user_id=user.user_id, actor_username=user.username, target_type="export", target_id=kind, detail={"rows": len(rows), "format": fmt})
    content = exports.to_xlsx(kind, rows) if fmt == "xlsx" else exports.to_csv(kind, rows)
    return content, exports.file_name(kind, datetime.now(timezone.utc).date(), fmt)
