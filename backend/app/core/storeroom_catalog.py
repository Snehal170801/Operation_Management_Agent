"""The Store Room: a read-only, organised view of everything the system has stored.

Every dataset here is defined by hand -- which columns, in which order, with what label -- so that
nothing a caller types ever reaches SQL (only a search term, as a bound parameter), and so that
sensitive tables can never be exposed by accident. Deliberately NOT included: Users, password hashes,
refresh tokens, one-time codes, the audit log (it has its own page), system settings and worker locks.
"""

from dataclasses import dataclass

# How the screen should draw a value:
#   text, longtext, int, money, rating, date, datetime  -> plain
#   note   -> a small highlighted remark (empty most of the time)
#   badge  -> coloured pill (statuses)
#   list   -> a JSON list stored as text, shown as separate lines
#   case   -> a case id, shown short and linked to the case
KINDS = frozenset({"note", "text", "longtext", "int", "money", "rating", "date", "datetime", "badge", "list", "case"})


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    expr: str          # SQL expression; selected AS key
    kind: str = "text"


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    group: str
    description: str
    columns: tuple[Column, ...]
    from_sql: str
    order_sql: str
    search_exprs: tuple[str, ...]   # SQL expressions a search term is matched against


DATASETS: tuple[Dataset, ...] = (
    # ---------------------------------------------------------------- Inventory
    Dataset(
        key="stock", label="Stock", group="Inventory",
        description="Every item held in the store room and how many are available.",
        columns=(
            Column("item", "Item", "s.item_description"),
            Column("quantity", "Available", "s.quantity_available", "int"),
            Column("level", "Level",
                   "CASE WHEN s.quantity_available <= 0 THEN 'out_of_stock' "
                   "WHEN s.quantity_available <= 5 THEN 'low' ELSE 'in_stock' END", "badge"),
            Column("updated", "Last updated", "s.updated_at", "datetime"),
            # Shown only while the latest change to the count was a cancelled request putting its goods back (any later change clears it).
            Column("note", "Note",
                   "(SELECT TOP 1 CASE WHEN l.reason = 'cancelled_returned' THEN 'Returned to stock (request cancelled)' END "
                   "FROM dbo.StockLedger l WHERE l.stock_id = s.stock_id ORDER BY l.created_at DESC, l.entry_id DESC)", "note"),
        ),
        from_sql="dbo.Stock s", order_sql="s.item_description ASC",
        search_exprs=("s.item_description",),
    ),
    # ---------------------------------------------------------------- Suppliers
    Dataset(
        key="suppliers", label="Suppliers", group="Suppliers",
        description="Approved suppliers, how reliable they are, and how much we have dealt with them.",
        columns=(
            Column("name", "Supplier", "v.name"),
            Column("email", "Email", "v.email"),
            Column("reliability", "Reliability", "v.reliability_score", "rating"),
            Column("quotes", "Quotes given", "(SELECT COUNT(*) FROM dbo.VendorQuotes q WHERE q.vendor_id = v.vendor_id)", "int"),
            Column("orders", "Orders placed", "(SELECT COUNT(*) FROM dbo.PurchaseOrders o WHERE o.vendor_id = v.vendor_id)", "int"),
            Column("added", "Added", "v.created_at", "datetime"),
        ),
        from_sql="dbo.Vendors v", order_sql="v.name ASC",
        search_exprs=("v.name", "v.email"),
    ),
    Dataset(
        key="rfqs", label="Quote requests", group="Suppliers",
        description="Each quote request sent to a supplier, and whether they replied.",
        columns=(
            Column("case", "Case", "r.case_id", "case"),
            Column("supplier", "Supplier", "v.name"),
            Column("status", "Status", "r.status", "badge"),
            Column("sent", "Sent", "r.sent_at", "datetime"),
            Column("deadline", "Reply due", "r.deadline_at", "datetime"),
            Column("reminders", "Reminders", "r.reminder_count", "int"),
            Column("replied", "Replied", "r.replied_at", "datetime"),
        ),
        from_sql="dbo.Rfqs r JOIN dbo.Vendors v ON v.vendor_id = r.vendor_id", order_sql="r.sent_at DESC",
        search_exprs=("v.name", "r.status", "CAST(r.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = r.case_id)"),
    ),
    Dataset(
        key="quotes", label="Quotes received", group="Suppliers",
        description="Every price a supplier has quoted, with the delivery time and terms the agent read.",
        columns=(
            Column("case", "Case", "q.case_id", "case"),
            Column("supplier", "Supplier", "v.name"),
            Column("price", "Price", "q.price", "money"),
            Column("days", "Delivery (days)", "q.lead_time_days", "int"),
            Column("terms", "Terms", "q.terms"),
            Column("text", "What they wrote", "LEFT(q.raw_quote_text, 300)", "longtext"),
            Column("received", "Received", "q.created_at", "datetime"),
        ),
        from_sql="dbo.VendorQuotes q JOIN dbo.Vendors v ON v.vendor_id = q.vendor_id", order_sql="q.created_at DESC",
        search_exprs=("v.name", "q.terms", "q.raw_quote_text", "CAST(q.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = q.case_id)"),
    ),
    Dataset(
        key="selections", label="Suppliers chosen", group="Suppliers",
        description="Which supplier the agent picked for each case, and why.",
        columns=(
            Column("case", "Case", "s.case_id", "case"),
            Column("supplier", "Chosen supplier", "v.name"),
            Column("why", "Why", "s.rationale", "longtext"),
            Column("chosen", "Chosen", "s.created_at", "datetime"),
        ),
        from_sql="dbo.VendorSelections s JOIN dbo.Vendors v ON v.vendor_id = s.vendor_id", order_sql="s.created_at DESC",
        search_exprs=("v.name", "s.rationale", "CAST(s.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = s.case_id)"),
    ),
    # ---------------------------------------------------------------- Requests
    Dataset(
        key="requests", label="Requests", group="Requests",
        description="Every purchase request: who asked, what for, and where it has got to.",
        columns=(
            Column("case", "Case", "c.case_id", "case"),
            Column("requester", "Requested by", "c.requester_id"),
            Column("request", "Their words", "pr.raw_request", "longtext"),
            Column("items", "Items", "it.items", "longtext"),
            Column("cost_center", "Cost center", "pr.cost_center"),
            Column("stage", "Stage", "c.stage", "badge"),
            Column("status", "Status", "c.status", "badge"),
            Column("created", "Created", "c.created_at", "datetime"),
            Column("updated", "Updated", "c.updated_at", "datetime"),
        ),
        from_sql=(
            "dbo.Cases c LEFT JOIN dbo.PurchaseRequests pr ON pr.case_id = c.case_id "
            "LEFT JOIN (SELECT purchase_request_id, "
            "STRING_AGG(CONCAT(description, ' (', quantity, ')'), ', ') WITHIN GROUP (ORDER BY created_at) AS items "
            "FROM dbo.PurchaseRequestItems GROUP BY purchase_request_id) it "
            "ON it.purchase_request_id = pr.purchase_request_id"
        ),
        order_sql="c.created_at DESC",
        search_exprs=("c.requester_id", "pr.raw_request", "it.items", "c.stage", "c.status",
                      "pr.cost_center", "CAST(c.case_id AS NVARCHAR(36))", "c.case_number"),
    ),
    Dataset(
        key="request_items", label="Requested items", group="Requests",
        description="The individual items inside each request.",
        columns=(
            Column("case", "Case", "pr.case_id", "case"),
            Column("item", "Item", "i.description"),
            Column("quantity", "Quantity", "i.quantity", "int"),
            Column("created", "Created", "i.created_at", "datetime"),
        ),
        from_sql="dbo.PurchaseRequestItems i JOIN dbo.PurchaseRequests pr ON pr.purchase_request_id = i.purchase_request_id",
        order_sql="i.created_at DESC",
        search_exprs=("i.description", "CAST(pr.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = pr.case_id)"),
    ),
    # ---------------------------------------------------------------- Orders & delivery
    Dataset(
        key="purchase_orders", label="Purchase orders", group="Orders & delivery",
        description="Every purchase order, whether it was emailed, and whether the goods have arrived.",
        columns=(
            Column("po", "PO", "CONCAT('PO-', po.po_number)"),
            Column("case", "Case", "po.case_id", "case"),
            Column("supplier", "Supplier", "v.name"),
            Column("total", "Total", "po.total_amount", "money"),
            Column("days", "Delivery (days)", "po.lead_time_days", "int"),
            Column("terms", "Terms", "po.terms"),
            Column("expected", "Expected by", "po.expected_delivery_date", "date"),
            Column("email", "Order email", "po.status", "badge"),
            Column("delivery", "Delivery", "po.delivery_status", "badge"),
            Column("chased", "Times chased", "po.chase_count", "int"),
            Column("received_by", "Received by", "po.received_by"),
            Column("received", "Received", "po.delivered_at", "datetime"),
            Column("created", "Created", "po.created_at", "datetime"),
        ),
        from_sql="dbo.PurchaseOrders po JOIN dbo.Vendors v ON v.vendor_id = po.vendor_id",
        order_sql="po.created_at DESC",
        search_exprs=("CONCAT('PO-', po.po_number)", "v.name", "po.status", "po.delivery_status",
                      "CAST(po.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = po.case_id)"),
    ),
    # ---------------------------------------------------------------- Finance
    Dataset(
        key="invoices", label="Invoices", group="Finance",
        description="Supplier invoices and whether they matched the order and the goods received.",
        columns=(
            Column("invoice", "Invoice", "i.invoice_number"),
            Column("supplier", "Supplier", "v.name"),
            Column("po", "PO", "CONCAT('PO-', po.po_number)"),
            Column("case", "Case", "i.case_id", "case"),
            Column("amount", "Amount", "i.total_amount", "money"),
            Column("status", "Status", "i.status", "badge"),
            Column("issues", "Problems found", "i.issues", "list"),
            Column("source", "Arrived by", "i.source"),
            Column("decided_by", "Decided by", "i.decided_by"),
            Column("received", "Received", "i.created_at", "datetime"),
        ),
        from_sql=("dbo.Invoices i JOIN dbo.Vendors v ON v.vendor_id = i.vendor_id "
                  "JOIN dbo.PurchaseOrders po ON po.purchase_order_id = i.purchase_order_id"),
        order_sql="i.created_at DESC",
        search_exprs=("i.invoice_number", "v.name", "CONCAT('PO-', po.po_number)", "i.status",
                      "CAST(i.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = i.case_id)"),
    ),
    # ---------------------------------------------------------------- Decisions
    Dataset(
        key="approvals", label="Approvals", group="Decisions",
        description="Every approval decision: made by policy automatically, or by a person.",
        columns=(
            Column("case", "Case", "a.case_id", "case"),
            Column("type", "About", "a.approval_type"),
            Column("status", "Status", "a.status", "badge"),
            Column("reasons", "Why a person was needed", "a.reasons", "list"),
            Column("decided_by", "Decided by", "a.decided_by"),
            Column("note", "Note", "a.decision_note", "longtext"),
            Column("asked", "Asked", "a.created_at", "datetime"),
            Column("decided", "Decided", "a.decided_at", "datetime"),
        ),
        from_sql="dbo.Approvals a", order_sql="a.created_at DESC",
        search_exprs=("a.status", "a.decided_by", "a.decision_note", "a.reasons", "CAST(a.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = a.case_id)"),
    ),
    # ---------------------------------------------------------------- Activity
    Dataset(
        key="events", label="Case activity", group="Activity",
        description="What happened on each case, newest first (the live agent step signals are on the Agent Flow page).",
        columns=(
            Column("id", "#", "e.event_id", "int"),
            Column("case", "Case", "e.case_id", "case"),
            Column("event", "What happened", "e.event_type"),
            Column("agent", "Agent", "e.agent_name"),
            Column("details", "Details", "LEFT(e.payload, 300)", "longtext"),
            Column("when", "When", "e.created_at", "datetime"),
        ),
        from_sql="(SELECT * FROM dbo.CaseEvents WHERE event_type NOT LIKE 'step.%') e", order_sql="e.event_id DESC",
        search_exprs=("e.event_type", "e.agent_name", "e.payload", "CAST(e.case_id AS NVARCHAR(36))", "(SELECT cn.case_number FROM dbo.Cases cn WHERE cn.case_id = e.case_id)"),
    ),
)

_BY_KEY = {d.key: d for d in DATASETS}

# Tables that must never appear here, whatever is added above (checked by a test).
FORBIDDEN_TABLES = (
    "dbo.Users", "dbo.RefreshTokens", "dbo.PasswordResetOtps", "dbo.AuditLog",
    "dbo.SystemSettings", "dbo.WorkerLeases", "dbo.Roles", "dbo.RolePermissions", "dbo.SchemaMigrations",
)


def get_dataset(key: str) -> Dataset | None:
    return _BY_KEY.get(key)


def groups() -> list[tuple[str, list[Dataset]]]:
    """Datasets grouped for display, in the order the groups first appear above."""
    order: dict[str, list[Dataset]] = {}
    for dataset in DATASETS:
        order.setdefault(dataset.group, []).append(dataset)
    return list(order.items())
