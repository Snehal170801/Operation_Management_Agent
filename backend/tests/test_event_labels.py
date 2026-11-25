"""Every event the backend can record has plain-English wording on the staff timeline, and the ones that reveal what a supplier did or why a person
was told stay out of a requester's view."""

import os
import re

import pytest

from app.core import agent_flow, case_access, stuck_policy, change_policy, combine, receipt

APP = os.path.join(os.path.dirname(__file__), "..", "app")
FRONTEND_LABELS = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "lib", "caseFlow.ts")

_CALL = re.compile(r'(?:publish_event|_signal_document)\(\s*[A-Za-z_\.\[\]"]+?\s*,\s*(f?)"([a-z_]+\.[a-z_{}\.]+)"')
# events whose name is held in a constant, and the ones that are about the system rather than one case
_CONSTANTS = {stuck_policy.STUCK_EVENT, stuck_policy.ESCALATED_EVENT, change_policy.CHANGE_REQUESTED, change_policy.CHANGE_HANDLED,
              combine.MERGED_INTO, combine.DISMISSED, combine.SUGGESTED, receipt.CONFIRMED, receipt.DISPUTED, receipt.HANDLED, "system.loop_restarted"}


def emitted() -> set[str]:
    found = set(_CONSTANTS)
    for root, _, files in os.walk(APP):
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    found.update(m.group(2) for m in _CALL.finditer(fh.read()))
    return found


def frontend_labels() -> set[str]:
    with open(FRONTEND_LABELS, encoding="utf-8") as fh:
        return set(re.findall(r"'([a-z_]+\.[a-z_]+)':", fh.read()))


def labelled(event_type: str, frontend: set[str]) -> bool:
    if event_type.startswith(("step.", "stage.")):
        return True                                                   # bookkeeping: the page shows them in its own way (or hides them)
    if "{" in event_type:                                             # approval.{status}: every real status has its own entry
        prefix = event_type.split("{")[0]
        return any(k.startswith(prefix) for k in {*agent_flow._DOMAIN_FEED, *agent_flow.EXTRA_LABELS, *frontend})
    return agent_flow.staff_label(event_type) is not None or event_type in frontend


def test_the_scan_really_finds_the_events():
    found = emitted()
    assert len(found) > 80 and {"case.created", "po.issued", "quote.question", "document.read", "case.stuck"} <= found


def test_every_event_the_backend_can_emit_has_a_plain_english_label():
    frontend = frontend_labels()
    missing = sorted(e for e in emitted() if not labelled(e, frontend))
    assert missing == [], f"No wording for: {missing}. Add a line to agent_flow._DOMAIN_FEED or EXTRA_LABELS."


@pytest.mark.parametrize("event_type", [
    "stock.returned", "case.owner_left", "approval.routed_to_admin", "approval.link_refused", "delivery.over_delivered", "delivery.before_confirmation",
    "quote.question", "quote.partial", "quote.declined", "quote.no_price", "email.duplicate", "email.auto_reply", "document.duplicate_file",
    "document.unsupported_file", "invoice.credit_note", "invoice.proforma", "invoice.after_close", "po.returned_unchanged",
    "delivery.claimed_by_supplier", "system.loop_restarted"])
def test_the_new_events_have_readable_staff_wording_and_no_raw_event_name(event_type):
    text = agent_flow.staff_label(event_type)
    assert text and not re.search(r"\b[a-z_]+\.[a-z_]+\b", text) and text[0].isupper()


def test_the_staff_only_events_never_reach_a_requester_s_feed_or_timeline():
    for event_type in agent_flow.STAFF_ONLY_FEED:
        e = {"event_type": event_type, "event_id": 1, "payload": {"vendor": "Acme", "price": 12345, "reason": "secret"}, "created_at": None}
        assert agent_flow._feed_line(e, staff=False) is None, event_type
        assert event_type not in case_access._REQUESTER_VISIBLE_EVENTS, event_type
        if event_type in agent_flow._DOMAIN_FEED:
            assert agent_flow._feed_line(e, staff=True) is not None, event_type


def test_a_requester_gets_no_label_and_staff_get_one(monkeypatch):
    from app.controllers import case_controller
    from app.models.auth_schemas import CurrentUser
    events = [{"event_id": 1, "event_type": "po.issued", "agent_name": "PO Agent", "payload": {"x": 1}, "created_at": __import__("datetime").datetime(2026, 1, 1)},
              {"event_id": 2, "event_type": "quote.question", "agent_name": "Vendor Agent", "payload": {"snippet": "?"}, "created_at": __import__("datetime").datetime(2026, 1, 2)}]
    monkeypatch.setattr(case_controller.operations_agent, "get_case_events", lambda cid: events)
    monkeypatch.setattr(case_controller.case_access, "assert_can_view", lambda user, cid: None)
    monkeypatch.setattr(case_controller.case_access.access, "has_permission", lambda role, permission: role == "staff")
    staff = case_controller.get_case_events("c", CurrentUser(user_id="1", username="s", role="staff"))
    assert [e.label for e in staff] == ["Order sent to the supplier", agent_flow.staff_label("quote.question")]
    mine = case_controller.get_case_events("c", CurrentUser(user_id="2", username="r", role="u_requester"))
    assert [e.event_type for e in mine] == ["po.issued"] and mine[0].label is None and mine[0].payload is None
