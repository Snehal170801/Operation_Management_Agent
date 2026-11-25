from app.agents import document_agent, invoice_agent, operations_agent, purchase_order_agent, vendor_agent
from app.core import case_access, document_index
from app.models.auth_schemas import CurrentUser
from app.models.document_store_schemas import DocumentPage


def _visible(user: CurrentUser) -> tuple[list[dict], bool]:
    """The documents this person may see, and whether it is the sanitised (requester) view."""
    staff = case_access.can_view_all(user)
    mine = case_access.requester_filter(user)
    cases = operations_agent.get_all_cases(mine)                         # a requester's list is already only their own cases
    by_id = {c["case_id"].lower(): c for c in cases}
    pos = [p for p in purchase_order_agent.list_purchase_orders() if staff or p["case_id"].lower() in by_id]
    invoices = [i for i in invoice_agent.list_invoices() if staff or i["case_id"].lower() in by_id]
    quotes = vendor_agent.list_all_quotes() if staff else []
    files = document_agent.list_read_files() if staff else []
    items = document_index.build(by_id, pos, invoices, quotes, files)
    if staff:
        return items, False
    return document_index.for_requester(items, set(by_id)), True


def search(user: CurrentUser, query: str | None, kind: str | None, limit: int, offset: int) -> DocumentPage:
    items, sanitised = _visible(user)
    return DocumentPage(**document_index.search(items, query, kind, limit, offset), sanitised=sanitised)


def for_case(user: CurrentUser, case_id: str) -> DocumentPage:
    """Every document of one case (404 for a case the person may not see)."""
    case_access.assert_can_view(user, case_id)
    items, sanitised = _visible(user)
    mine = [i for i in items if i["case_id"].lower() == case_id.lower()]
    return DocumentPage(**document_index.search(mine, None, None, document_index.MAX_LIMIT, 0), sanitised=sanitised)
