from app.agents import delivery_agent, purchase_order_agent
from app.core.config import settings
from app.core.exceptions import PurchaseOrderNotFound
from app.core.suggestions import invoice_suggestion


def attach_suggestions(invoices: list[dict]) -> list[dict]:
    """Each invoice with a one-sentence `suggestion` and a `verdict` (match | waiting | mismatch | check) added, worked out
    against its purchase order and whether the goods were received. Reads each case's order and delivery once."""
    orders: dict[str, dict | None] = {}
    received: dict[str, bool] = {}
    out = []
    for inv in invoices:
        case_id = inv["case_id"]
        if case_id not in orders:
            orders[case_id] = purchase_order_agent.find_purchase_order(case_id)
            try:
                received[case_id] = delivery_agent.get_delivery(case_id)["delivery_status"] == "delivered"
            except PurchaseOrderNotFound:
                received[case_id] = False
        s = invoice_suggestion(inv, orders[case_id], received[case_id], settings.INVOICE_AMOUNT_TOLERANCE_PCT)
        out.append({**inv, "suggestion": s["text"] if s else None, "verdict": s["verdict"] if s else None})
    return out
