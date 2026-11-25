import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import require_permission, require_resource
from app.api.routes import (
    agent_flow,
    approvals,
    audit,
    auth,
    calls,
    case_changes,
    combine,
    config,
    cases,
    dashboard,
    decisions,
    delivery,
    document_store,
    documents,
    exports,
    goods_issues,
    invoices,
    live,
    my_work,
    presence,
    notifications,
    purchase_order_list,
    purchase_orders,
    purchase_requests,
    receipt,
    reports,
    stock,
    storeroom,
    system,
    unmatched_documents,
    users,
    vendors,
)
from app.core import access, heartbeat, tunables
from app.core.live import hub as live_hub
from app.core.config import settings
from app.core.error_handlers import register_error_handlers
from app.core.logging import setup_logging
from app.core.request_guard import RequestGuard
from app.orchestrator import worker
from app.orchestrator.supervisor import Supervisor, supervise_forever

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Admin always holds every permission; the built-in permission sets get their defaults the first time.
        access.sync_system_roles()
    except Exception:
        logging.getLogger("app").exception("could not sync system roles (is the database migrated?)")
    try:
        tunables.refresh()  # settings changed in the Configure tab
    except Exception:
        logging.getLogger("app").exception("could not load saved configuration")
    live_hub.attach(asyncio.get_running_loop())
    if settings.WORKER_ENABLED:  # tell the health monitor which background jobs are meant to be running
        heartbeat.expect(heartbeat.WORKER)
        if settings.IMAP_HOST:
            heartbeat.expect(heartbeat.MAILBOX)
    supervisor = Supervisor({heartbeat.WORKER: worker.run_forever, heartbeat.MAILBOX: worker.watch_mailbox_forever}) if settings.WORKER_ENABLED else None
    tasks: list = []
    if supervisor:
        supervisor.start()           # the two loops that can go quiet; the supervisor restarts them (see orchestrator/supervisor.py)
        tasks = [asyncio.create_task(worker.watch_health_forever()), asyncio.create_task(supervise_forever(supervisor))]
    yield
    for task in tasks:
        task.cancel()
    if supervisor:
        supervisor.stop()


app = FastAPI(title="Operation Agents API", lifespan=lifespan)

# Added before CORS so it sits inside it: its error answers still carry the CORS headers the browser needs.
app.add_middleware(RequestGuard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    # The refresh token travels in an httpOnly cookie, so credentials must be allowed
    # (which is why CORS_ORIGINS can never be "*").
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

# /auth handles its own access rules (login/refresh/logout are public, /me is guarded).
app.include_router(auth.router)
app.include_router(decisions.router)         # public: the link in an approval email is the credential

# Everything else requires a valid access token AND a permission.
# Staff-only sections are guarded per resource (GET -> "<resource>:read", otherwise
# "<resource>:write"); see app/core/permissions.py.
_GUARDED_ROUTERS = (
    (stock, require_resource("stock")),
    (vendors, require_resource("vendors")),
    (approvals, require_resource("approvals")),
    # Purchase orders and deliveries carry amounts and vendor details: staff only.
    # Viewing needs "view all"; each action below needs its own department's permission (see the routes).
    (purchase_orders, require_permission("cases:read_all")),
    (purchase_order_list, require_permission("cases:read_all")),
    (delivery, require_permission("cases:read_all")),
    (unmatched_documents, require_permission("cases:read_all")),     # supplier documents that named no order (list for all staff; Accounts and the Vendor team act)
    (invoices, require_permission("cases:read_all")),
    (documents, require_permission("cases:read_all")),   # printable PO and approval summary: prices and reasons, staff only
)
for module, guard in _GUARDED_ROUTERS:
    app.include_router(module.router, dependencies=[Depends(guard)])

# Cases and purchase requests are open to requesters too, so these routers guard each route
# themselves and limit what a requester gets to their OWN cases (see app/core/case_access.py).
app.include_router(cases.router)
app.include_router(document_store.router)       # each route scopes what it returns to the person
app.include_router(exports.router)         # each route names its own permission
app.include_router(goods_issues.router)
app.include_router(case_changes.router)
app.include_router(combine.router)
app.include_router(receipt.router)
app.include_router(notifications.router)
app.include_router(live.router)
app.include_router(my_work.router)
app.include_router(presence.router)
app.include_router(agent_flow.router)
app.include_router(dashboard.router)
app.include_router(storeroom.router)
app.include_router(purchase_requests.router)

# Admin-only routers declare their own permission per route.
app.include_router(users.router)

# Demo phone calls: staff starts one (signed-in).
app.include_router(calls.router)
app.include_router(audit.router)
app.include_router(system.router)
app.include_router(reports.router)
app.include_router(config.router)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
