"""The permission catalog: every permission the API knows about.

Permissions are `resource:action` strings checked by the route guards. What each USER may do is
data (ticked per user in the Users screen); this file only defines what exists, how it is grouped
for that screen, and the defaults the built-in permission sets start with.

Per module the screen offers a few "levels" (Read only, CRUD, ...). A level is just a named bundle
of the permissions below, so ticking a box never hides what is really being granted.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class Level:
    """One checkbox on the Users screen: ticking it grants `permissions`."""

    key: str
    label: str
    permissions: tuple[str, ...]
    # Levels that must also be ticked (CRUD includes Read only).
    implies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceGroup:
    resource: str
    label: str
    permissions: tuple[Permission, ...]
    levels: tuple[Level, ...]


def _read(*perms: str) -> Level:
    return Level("read", "Read only", perms)


def _crud(*perms: str) -> Level:
    return Level("crud", "CRUD", perms, implies=("read",))


CATALOG: tuple[ResourceGroup, ...] = (
    ResourceGroup("dashboard", "Dashboard", (
        Permission("dashboard:read", "View", "See the dashboard and its totals."),
    ), (_read("dashboard:read"),)),
    ResourceGroup("cases", "Cases & purchase orders", (
        Permission("cases:read", "View own", "See the requests you submitted and the progress of the agents on them."),
        Permission("cases:read_all", "View all", "See every case, purchase request, purchase order and delivery - full detail."),
        Permission("cases:create", "Submit requests", "Submit a purchase request (creates a case owned by you)."),
        Permission("cases:write", "Act on cases", "Retry purchase orders, confirm deliveries and other staff actions on cases."),
    ), (
        # Requesters: submit requests and follow only their own cases.
        Level("own", "Own requests only", ("cases:read", "cases:create")),
        _read("cases:read", "cases:read_all"),
        _crud("cases:read", "cases:read_all", "cases:create", "cases:write"),
    )),
    ResourceGroup("stock", "Stock", (
        Permission("stock:read", "View", "See stock levels."),
        Permission("stock:write", "Create & change", "Add or update stock."),
    ), (_read("stock:read"), _crud("stock:read", "stock:write"))),
    ResourceGroup("vendors", "Vendors & quotes", (
        Permission("vendors:read", "View", "See vendors and quotes."),
        Permission("vendors:write", "Create & change", "Add vendors, submit quotes, rank vendors."),
    ), (_read("vendors:read"), _crud("vendors:read", "vendors:write"))),
    ResourceGroup("approvals", "Approvals", (
        Permission("approvals:read", "View", "See approval requests."),
        Permission("approvals:write", "Decide", "Approve or reject requests."),
    ), (_read("approvals:read"), _crud("approvals:read", "approvals:write"))),
    ResourceGroup("po", "Purchase orders", (
        Permission("po:manage", "Retry & re-send", "Retry or re-send a purchase order that could not be created or emailed."),
    ), (Level("manage", "Manage", ("po:manage",)),)),
    ResourceGroup("delivery", "Delivery", (
        Permission("delivery:confirm", "Confirm goods received", "Confirm that the goods arrived. This stops the supplier follow-ups and lets the invoice be matched."),
    ), (Level("confirm", "Confirm receipt", ("delivery:confirm",)),)),
    ResourceGroup("invoices", "Invoices", (
        Permission("invoices:decide", "Decide invoices", "Enter an invoice by hand, and approve or reject one that does not match."),
    ), (Level("decide", "Decide", ("invoices:decide",)),)),
    ResourceGroup("storeroom", "Store Room", (
        Permission("storeroom:read", "View", "Browse and export all stored operational data (read-only)."),
    ), (_read("storeroom:read"),)),
    ResourceGroup("users", "Users", (
        Permission("users:read", "View", "See the user list."),
        Permission("users:write", "Manage", "Create users, edit them and their access, reset passwords, unlock accounts."),
    ), (_read("users:read"), _crud("users:read", "users:write"))),
    ResourceGroup("audit", "Audit log", (
        Permission("audit:read", "View", "Read the audit log."),
    ), (_read("audit:read"),)),
    ResourceGroup("system", "System", (
        Permission("system:read", "View health", "See system health and whether automation is running."),
        Permission("system:write", "Control automation", "Pause and resume the automatic agents, and change the Configure settings (reminder times, limits)."),
    ), (_read("system:read"), _crud("system:read", "system:write"))),
)

ALL_PERMISSIONS: frozenset[str] = frozenset(p.key for g in CATALOG for p in g.permissions)

_VIEW = (
    "dashboard:read",
    "cases:read",
    "stock:read",
    "vendors:read",
    "approvals:read",
)

# Starting permissions for the built-in permission sets. `admin` is special: it always holds everything.
# `user` is the requester: submits requests and watches the agents work on THEIR OWN cases only
# (no stock, vendors, prices, approvals or other people's cases).
DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "user": frozenset(("cases:read", "cases:create")),
    "viewer": frozenset(_VIEW + ("cases:read_all", "storeroom:read")),
    "manager": frozenset(
        _VIEW + ("cases:read_all", "storeroom:read", "cases:create", "cases:write", "stock:write", "vendors:write", "approvals:write",
                 "po:manage", "delivery:confirm", "invoices:decide")
    ),
    "admin": ALL_PERMISSIONS,
}



@dataclass(frozen=True)
class Department:
    """One agent's human counterpart: the people asked when that agent is stuck. A person can belong to several."""

    key: str
    label: str
    agent: str
    handles: str
    permissions: tuple[str, ...]


_BASE = ("dashboard:read", "cases:read", "cases:read_all")

DEPARTMENTS: tuple[Department, ...] = (
    Department("purchase", "Purchase desk", "Purchase Agent", "Requests the AI could not read or that look wrong",
               _BASE + ("cases:create", "cases:write", "storeroom:read")),
    Department("procurement", "Stores", "Procurement Agent", "Stock levels and the Store Room",
               _BASE + ("stock:read", "stock:write", "storeroom:read")),
    Department("vendor", "Vendor team", "Vendor Agent", "Suppliers that don't reply, and the quotes",
               _BASE + ("vendors:read", "vendors:write", "stock:read")),
    Department("approval", "Approvers", "Approval Agent", "Orders too big or risky to approve automatically",
               _BASE + ("approvals:read", "approvals:write", "vendors:read")),
    Department("po", "PO desk", "PO Agent", "Purchase orders that could not be created or emailed",
               _BASE + ("po:manage", "vendors:read")),
    Department("delivery", "Receiving", "Delivery Agent", "Confirming goods arrived, and late deliveries",
               _BASE + ("delivery:confirm",)),
    Department("invoice", "Accounts", "Invoice Agent", "Invoices that don't match the order",
               _BASE + ("invoices:decide",)),
)

# Who is asked about what: the permission that marks the right people for each kind of problem.
# If nobody holds it, the alert falls back to whoever can control the system (the admins).
ALERT_PERMISSION = {
    "approval": "approvals:write", "vendor": "vendors:write", "po": "po:manage",
    "delivery": "delivery:confirm", "invoice": "invoices:decide", "procurement": "stock:write",
}
ALERT_FALLBACK_PERMISSION = "system:write"

SYSTEM_ROLES = ("admin", "manager", "viewer", "user")
ADMIN_ROLE = "admin"

# Each non-admin user's ticks are stored as their own private permission set, named after the user.
# Nobody sees these as "roles": it is just where one user's checkmarks live.
PRIVATE_PREFIX = "u_"


def private_role_name(user_id: str) -> str:
    return PRIVATE_PREFIX + user_id.replace("-", "").lower()[:12]


def is_private_role(name: str) -> bool:
    return name.startswith(PRIVATE_PREFIX)


# A non-admin can never remove this from themselves (it would lock them out of user management).
LOCKOUT_PERMISSIONS = ("users:write",)
