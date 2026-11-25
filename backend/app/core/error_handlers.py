from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    CaseNotFound,
    PurchaseRequestNotFound,
    NoQuotesFound,
    VendorSelectionNotFound,
    ApprovalNotFound,
    ApprovalAlreadyDecided,
    PurchaseOrderNotFound,
    DeliveryAlreadyConfirmed,
    TooManyRequests,
    DatasetNotFound,
    InvoiceNotFound,
    InvoiceAlreadyDecided,
    NotAnInvoice,
    VendorNotApproved,
    InvalidStageTransition,
    QuoteExpired,
    DocumentAlreadyHandled,
    DocumentNotFound,
    LinkProblem,
    InvalidCredentials,
    InvalidToken,
    AccountLocked,
    Forbidden,
    UserNotFound,
    UsernameTaken,
    WeakPassword,
    RuleViolation,
    InvalidOtp,
    EmailTaken,
    RoleNotFound,
    InvalidInput,
    StockItemNotFound,
    VendorNotFound,
)

# exception type -> HTTP status code
_STATUS_BY_EXCEPTION = {
    CaseNotFound: 404,
    PurchaseRequestNotFound: 404,
    NoQuotesFound: 404,
    VendorSelectionNotFound: 404,
    ApprovalNotFound: 404,
    ApprovalAlreadyDecided: 409,
    PurchaseOrderNotFound: 404,
    DeliveryAlreadyConfirmed: 409,
    TooManyRequests: 429,
    DatasetNotFound: 404,
    InvoiceNotFound: 404,
    InvoiceAlreadyDecided: 409,
    NotAnInvoice: 422,
    VendorNotApproved: 409,
    InvalidStageTransition: 409,
    InvalidCredentials: 401,
    InvalidToken: 401,
    AccountLocked: 423,
    Forbidden: 403,
    UserNotFound: 404,
    UsernameTaken: 409,
    WeakPassword: 422,
    RuleViolation: 409,
    DocumentNotFound: 404,
    DocumentAlreadyHandled: 409,
    InvalidOtp: 400,
    EmailTaken: 409,
    RoleNotFound: 404,
    InvalidInput: 422,
    QuoteExpired: 409,
    StockItemNotFound: 404,
    VendorNotFound: 404,
}


def _link_problem(request: Request, exc: Exception):
    # "not valid" is a 404; every other reason (used, expired...) is a 410, "gone". The words never say more than the key.
    return JSONResponse(status_code=404 if exc.key == "invalid" else 410, content={"detail": str(exc), "reason": exc.key})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LinkProblem, _link_problem)
    for exc_type, status_code in _STATUS_BY_EXCEPTION.items():

        def handler(request: Request, exc: Exception, _status: int = status_code):
            headers = {"WWW-Authenticate": "Bearer"} if _status == 401 else None
            return JSONResponse(status_code=_status, content={"detail": str(exc)}, headers=headers)

        app.add_exception_handler(exc_type, handler)
