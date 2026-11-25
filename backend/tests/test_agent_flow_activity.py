"""The live "what just happened" feed returned with each agent flow."""

import pytest

from app.core.agent_flow import ACTIVITY_LIMIT, _DOMAIN_FEED
from app.core.agent_steps import STEPS

from .fake_world import World, standard_world
from .test_agent_flow import Log, flow, live


def feed(result):
    return result["activity"]


# ---------- step events become readable lines, newest first ----------

def test_the_feed_shows_steps_starting_and_finishing_newest_first():
    log = Log().start("check_stock", "a").finish("check_stock", "a", seconds=2.0).start("request_quotes", "b")
    items = feed(flow("sourcing_needed", log=log))
    assert [i["text"] for i in items] == [
        "Asking suppliers for prices", "Finished: checking stock (2.0 s)", "Checking stock"]
    assert [i["tone"] for i in items] == ["info", "ok", "info"]
    assert [i["agent"] for i in items] == ["Vendor", "Procurement", "Procurement"]
    assert items[0]["id"] > items[1]["id"] > items[2]["id"]


def test_progress_updates_are_not_separate_lines():
    log = Log().start("check_stock").progress("check_stock", 1, 3, "Laptop").progress("check_stock", 2, 3, "Mouse")
    assert [i["text"] for i in feed(flow("purchase_request_created", log=log))] == ["Checking stock"]


def test_the_feed_is_capped_to_the_latest_few():
    log = Log()
    for n in range(ACTIVITY_LIMIT + 6):
        log.start("read_quote", f"r{n}").finish("read_quote", f"r{n}")
    items = feed(flow("awaiting_quotes", log=log))
    assert len(items) == ACTIVITY_LIMIT
    assert items[0]["id"] == max(e["event_id"] for e in log.events)


def test_a_case_with_no_events_has_an_empty_feed():
    assert feed(flow("created")) == []


# ---------- hand-offs outside a tracked step ----------

@pytest.mark.parametrize("event_type", sorted(_DOMAIN_FEED))
def test_each_known_hand_off_has_its_fixed_wording(event_type):
    agent, text, tone = _DOMAIN_FEED[event_type]
    [item] = feed(flow("po_issued", log=Log().add(event_type)))
    assert (item["agent"], item["text"], item["tone"]) == (agent, text, tone)


def test_events_we_do_not_list_stay_out_of_the_feed():
    log = Log().add("notification.sent", {"kind": "approval_requested", "sent": 2}).add("quote.submitted", {"price": 42000})
    assert feed(flow("awaiting_quotes", log=log)) == []


# ---------- what a requester must never see ----------

def test_a_requester_gets_a_gentle_failure_line_and_staff_get_the_error():
    log = Log().start("read_request").fail("read_request", error="Azure OpenAI timed out at https://secret.example")
    requester = feed(flow("created", log=log, audience="requester"))[0]
    staff = feed(flow("created", log=log, audience="staff"))[0]
    assert requester["text"] == "Ran into a problem: reading your request. Our team has been told."
    assert "secret" not in requester["text"] and "timed out" in staff["text"]
    assert requester["tone"] == staff["tone"] == "bad"


def test_payloads_never_reach_a_requesters_feed():
    log = (Log().add("approval.requested", {"reasons": ["Amount 90,000 exceeds the limit"], "vendor": "Acme"})
           .add("po.issued", {"po_number": "PO-1001", "vendor": "Acme", "total_amount": 42000})
           .add("vendor.selected", {"vendor_id": "v1", "rationale": "Acme is cheapest at 42000"}))
    text = str(feed(flow("po_issued", log=log, audience="requester")))
    for secret in ("Acme", "90,000", "42000", "PO-1001", "cheapest", "reasons"):
        assert secret not in text


def test_step_labels_in_the_feed_come_only_from_the_safe_catalogue():
    log = Log()
    for key in STEPS:
        log.start(key, key).finish(key, key)
    labels = {s.label.lower() for s in STEPS.values()}
    for item in feed(flow("awaiting_quotes", log=log, audience="requester")):
        assert item["text"].startswith("Finished: ") is False or item["text"][len("Finished: "):].split(" (")[0] in labels


# ---------- the real flow ----------

@pytest.fixture
def w(monkeypatch) -> World:
    return standard_world(monkeypatch)


def test_a_real_request_produces_a_readable_story(w):
    case_id = w.submit("50 cameras")
    texts = [i["text"] for i in live(w, case_id, "requester")["activity"]]
    # newest first: the suppliers were just asked, before that stock was checked, before that the request was read
    assert texts[:3] == ["Finished: asking suppliers for prices", "Asking suppliers for prices", "Finished: checking stock"]
    assert "Reading your request" in texts


def test_the_feed_grows_as_the_case_moves_on(w):
    case_id = w.submit("50 cameras")
    before = live(w, case_id)["activity"][0]["id"]
    for vendor, text in {"Acme": "Total Rs 42,000. Delivery 7 days. Terms: net 30",
                         "Globex": "Total Rs 45,000. Delivery 5 days. Terms: net 30"}.items():
        w.reply(case_id, vendor, text)
    w.expire_quote_deadline(case_id)
    w.tick()
    after = live(w, case_id)["activity"]
    assert after[0]["id"] > before
    assert "Order sent to the supplier" in [i["text"] for i in after]
