class CaseNotFound(Exception):
    def __init__(self, case_id: str):
        self.case_id = case_id
        super().__init__(f"No case found with id {case_id}")


class PurchaseRequestNotFound(Exception):
    def __init__(self, case_id: str):
        self.case_id = case_id
        super().__init__(f"No purchase request found for case {case_id}")


class NoQuotesFound(Exception):
    def __init__(self, case_id: str):
        self.case_id = case_id
        super().__init__(f"No vendor quotes found for case {case_id}")


class VendorSelectionNotFound(Exception):
    def __init__(self, case_id: str):
        self.case_id = case_id
        super().__init__(f"No vendor has been selected yet for case {case_id}")


class PurchaseOrderNotFound(Exception):
    def __init__(self, case_id: str):
        self.case_id = case_id
        super().__init__(f"No purchase order has been issued for case {case_id}")


class StockItemNotFound(Exception):
    def __init__(self, item: str):
        self.item = item
        super().__init__(f"There is no stock item called '{item}'.")


class VendorNotFound(Exception):
    def __init__(self, vendor_id: str):
        self.vendor_id = vendor_id
        super().__init__("There is no such supplier.")


class DatasetNotFound(Exception):
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"There is no Store Room section called '{key}'")


class InvoiceNotFound(Exception):
    def __init__(self, invoice_id: str):
        self.invoice_id = invoice_id
        super().__init__(f"No invoice found with id {invoice_id}")


class InvoiceAlreadyDecided(Exception):
    def __init__(self, invoice_id: str):
        self.invoice_id = invoice_id
        super().__init__(f"Invoice {invoice_id} is no longer waiting for a decision")


class NotAnInvoice(Exception):
    def __init__(self):
        super().__init__("That text does not look like an invoice (no invoice, or nothing readable in it).")


class TooManyRequests(Exception):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"Daily request limit reached ({limit}). Please try again tomorrow.")


class DeliveryAlreadyConfirmed(Exception):
    def __init__(self, case_id: str):
        self.case_id = case_id
        super().__init__(f"Delivery for case {case_id} has already been confirmed")


class VendorNotApproved(Exception):
    def __init__(self, case_id: str):
        self.case_id = case_id
        super().__init__(f"Case {case_id} has no approved vendor selection yet")


class ApprovalNotFound(Exception):
    def __init__(self, approval_id: str):
        self.approval_id = approval_id
        super().__init__(f"No approval found with id {approval_id}")


class ApprovalAlreadyDecided(Exception):
    def __init__(self, approval_id: str):
        self.approval_id = approval_id
        super().__init__(f"Approval {approval_id} is no longer pending")


class InvalidStageTransition(Exception):
    def __init__(self, case_id: str, from_stage: str, to_stage: str):
        self.case_id = case_id
        self.from_stage = from_stage
        self.to_stage = to_stage
        super().__init__(f"Case {case_id} cannot move from '{from_stage}' to '{to_stage}'")


class InvalidCredentials(Exception):
    def __init__(self, message: str = "Invalid username or password"):
        super().__init__(message)


class AccountLocked(Exception):
    def __init__(self, retry_after_minutes: int):
        self.retry_after_minutes = retry_after_minutes
        super().__init__(
            f"Too many failed sign-in attempts. Try again in {retry_after_minutes} minute(s)."
        )


class InvalidToken(Exception):
    def __init__(self, message: str = "Invalid or expired session"):
        super().__init__(message)


class Forbidden(Exception):
    def __init__(self, message: str = "You do not have permission to do that"):
        super().__init__(message)


class UserNotFound(Exception):
    def __init__(self):
        super().__init__("User not found")


class UsernameTaken(Exception):
    def __init__(self, username: str):
        super().__init__(f"Username '{username}' is already taken")


class WeakPassword(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)


class RuleViolation(Exception):
    """A business rule blocks the action (e.g. removing the last admin)."""


class InvalidOtp(Exception):
    """Deliberately vague: wrong, expired, used and unknown-account all look the same."""

    def __init__(self):
        super().__init__("Invalid or expired code")


class EmailTaken(Exception):
    def __init__(self, email: str):
        super().__init__(f"Email '{email}' is already used by another account")


class RoleNotFound(Exception):
    def __init__(self):
        super().__init__("Role not found")


class InvalidInput(Exception):
    """A request that is well-formed JSON but not acceptable (unknown permission, unknown role...)."""


class DocumentNotFound(Exception):
    """No such unmatched document."""


class DocumentAlreadyHandled(Exception):
    """Someone has already attached or dismissed this document."""


class QuoteExpired(Exception):
    """The supplier's quote is no longer valid, so the order was not placed; the supplier has been asked to refresh it."""


class LinkProblem(Exception):
    """An email decision link cannot be used. `key` says why (see core/email_approval.MESSAGES); the text shown is always generic."""

    def __init__(self, key: str):
        from app.core.email_approval import MESSAGES
        self.key = key
        super().__init__(MESSAGES.get(key, MESSAGES["invalid"]))
