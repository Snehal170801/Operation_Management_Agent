"""The things each agent does, as named steps.

Every step is recorded on the case as it happens (step.started -> step.progress -> step.finished /
step.failed), so the Agent Flow page can show what is REALLY being worked on right now instead of
guessing from what has finished. The labels here are friendly and safe to show a requester: they say
what is happening, never prices, supplier names or reasons.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    agent: str
    label: str  # present tense, plain words


# The agents drawn on the Agent Flow page, in the order a request travels through them.
FLOW_AGENTS: tuple[str, ...] = (
    "Purchase Agent",
    "Procurement Agent",
    "Vendor Agent",
    "Approval Agent",
    "PO Agent",
    "Delivery Agent",
    "Invoice Agent",
)

STEPS: dict[str, Step] = {
    s.key: s
    for s in (
        Step("read_request", "Purchase Agent", "Reading your request"),
        Step("check_stock", "Procurement Agent", "Checking stock"),
        Step("request_quotes", "Vendor Agent", "Asking suppliers for prices"),
        Step("remind_suppliers", "Vendor Agent", "Reminding suppliers who haven't replied"),
        Step("read_quote", "Vendor Agent", "Reading a supplier's quote"),
        Step("rank_quotes", "Vendor Agent", "Comparing the quotes"),
        Step("review_approval", "Approval Agent", "Checking the approval rules"),
        Step("issue_po", "PO Agent", "Preparing and sending the order"),
        Step("withdraw_request", "Vendor Agent", "Telling suppliers the request is withdrawn"),
        Step("chase_po_confirmation", "PO Agent", "Asking the supplier to confirm the order"),
        Step("chase_delivery", "Delivery Agent", "Following up on delivery"),
        Step("chase_invoice", "Invoice Agent", "Asking the supplier for a corrected invoice"),
        Step("read_invoice", "Invoice Agent", "Reading the invoice"),
        Step("match_invoice", "Invoice Agent", "Matching it against the order"),
    )
}

# Event types written for steps.
STEP_STARTED = "step.started"
STEP_PROGRESS = "step.progress"
STEP_FINISHED = "step.finished"
STEP_FAILED = "step.failed"
STEP_EVENTS = frozenset({STEP_STARTED, STEP_PROGRESS, STEP_FINISHED, STEP_FAILED})
