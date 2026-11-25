"""The last safety net around every request.

* Gives each request a short reference (`X-Request-ID`), puts it on the response and in the log line for any failure, so
  "it said ref 4f2a9c1b" is enough to find exactly what went wrong.
* Turns an error nobody planned for into a clean JSON answer instead of a plain-text 500. Because this sits inside the
  CORS layer the browser can read that answer (an unplanned error that escapes outward loses the CORS headers, and the
  browser then shows a confusing "network error").
* Says "the database is not reachable" (503, try again) separately from "something broke" (500).
* Never shows the person the exception text: it can hold SQL, paths or secrets. That goes to the log only.

Plain ASGI rather than BaseHTTPMiddleware so the live (event-stream) connection is never buffered or cut.
"""

import logging
import uuid

from fastapi.responses import JSONResponse

from app.db.connection import is_connection_problem

logger = logging.getLogger("app.errors")

HEADER = b"x-request-id"


def classify(exc: BaseException) -> tuple[int, str]:
    if is_connection_problem(exc):
        return 503, "The database is not reachable right now. Please try again in a moment."
    return 500, "Something went wrong on our side. Please try again. If it keeps happening, tell support and quote the reference."


class RequestGuard:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(HEADER, b"").decode("latin-1")[:40]
        rid = incoming if incoming.isalnum() else uuid.uuid4().hex[:8]
        started = False

        async def send_with_id(message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = {**message, "headers": [*message.get("headers", []), (HEADER, rid.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as exc:
            logger.exception("Unhandled error on %s %s [ref %s]", scope.get("method"), scope.get("path"), rid)
            if started:  # the answer was already on its way (e.g. a stream): nothing can be changed now
                raise
            status, message = classify(exc)
            response = JSONResponse(status_code=status, content={"detail": message, "request_id": rid})
            await response(scope, receive, send_with_id)
