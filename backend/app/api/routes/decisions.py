from fastapi import APIRouter, HTTPException, Request

from app.controllers import decision_controller
from app.core.rate_limit import RateLimit
from app.models.decision_schemas import DecisionInfo, DecisionRequest, DecisionResult

# PUBLIC: no login. The link itself is the credential (made for one person, one approval, used once, expires). Every call is
# limited per caller address so a stranger cannot try guesses quickly.
router = APIRouter(prefix="/decisions", tags=["decisions"])

_limit = RateLimit(limit=40, window_seconds=600)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _guard(request: Request) -> str:
    ip = _ip(request)
    if not _limit.allow(ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a few minutes and try again.")
    return ip


@router.get("/{token}", response_model=DecisionInfo)
def info(token: str, request: Request):
    """Show the order the link is for. Changes nothing."""
    _guard(request)
    return decision_controller.get_info(token)


@router.post("/{token}", response_model=DecisionResult)
def decide(token: str, body: DecisionRequest, request: Request):
    """The confirming tap: approve or refuse. Works once."""
    ip = _guard(request)
    return decision_controller.decide(token, body.action, body.note, ip)
