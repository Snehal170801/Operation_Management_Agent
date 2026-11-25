from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permission
from app.controllers import report_controller
from app.models.report_schemas import Report

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_permission("dashboard:read"))])


@router.get("", response_model=Report)
def get_report(days: int = Query(default=90, ge=0, le=report_controller.MAX_DAYS)):
    """Spend, stage times, how much ran with no person, and supplier scorecards, for the last `days` days (0 = all time)."""
    return report_controller.get_report(days)
