import asyncio
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import require_permission
from app.core import case_access
from app.core.live import hub
from app.models.auth_schemas import CurrentUser

router = APIRouter(prefix="/live", tags=["live"])

HEARTBEAT_SECONDS = 15
# A connection is renewed every few minutes, so a person who is deactivated or whose access changes is cut off
# soon (the page reconnects with its refreshed login, and is refused if it no longer has one).
MAX_LIFETIME_SECONDS = 10 * 60


async def event_stream(sub, heartbeat: float = HEARTBEAT_SECONDS, lifetime: float = MAX_LIFETIME_SECONDS):
    """The text/event-stream body: a greeting, then each signal as it comes, a quiet ping while idle."""
    ends_at = time.monotonic() + lifetime
    try:
        yield "retry: 3000\n\n"
        yield 'data: {"t": "hello"}\n\n'
        while time.monotonic() < ends_at:
            try:
                message = await asyncio.wait_for(sub.queue.get(), min(heartbeat, max(0.05, ends_at - time.monotonic())))
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            yield f"data: {message}\n\n"
    finally:
        hub.unsubscribe(sub)


@router.get("/stream")
async def stream(user: CurrentUser = Depends(require_permission("cases:read"))):
    """Open-ended stream of "a case changed" signals for the signed-in person. Staff hear about every case,
    a requester only about their own. The signal says nothing about the content; the page re-reads that."""
    sub = hub.subscribe(user.username, case_access.can_view_all(user))
    return StreamingResponse(
        event_stream(sub),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
