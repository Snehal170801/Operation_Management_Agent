"""Deciding an approval from the email in one tap: safe by construction (one person, one approval, once, expires, confirm first)."""

import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents import approval_agent, purchase_order_agent
from app.controllers import decision_controller
from app.core import access, email_approval as ea
from app.core import rate_limit
from app.core.config import settings
from app.core.exceptions import LinkProblem, RuleViolation
from app.main import app
from app.repositories import role_repository, user_repository

from .fake_world import World, now, standard_world
from .test_end_to_end import QUOTE_42K, QUOTE_45K, source

NOW = datetime(2026, 3, 2, 9)
MANAGER = "00000000-0000-0000-0000-000000000000"
client = TestClient(app)


# ---- the rules ----

def test_buttons_are_only_offered_within_the_limit_and_when_switched_on():
    assert ea.offer_link(True, 90000, 100000, "vendor_selection")
    assert not ea.offer_link(True, 100001, 100000, "vendor_selection")
    assert not ea.offer_link(True, None, 100000, "vendor_selection")                # unknown amount: a person looks in the app
    assert not ea.offer_link(False, 1000, 100000, "vendor_selection")
    assert not ea.offer_link(True, 1000, 0, "vendor_selection")                      # a limit of 0 switches them off
    assert ea.offer_link(True, 28000, 100000, "price_change") and not ea.offer_link(True, 280000, 100000, "price_change")


def test_why_a_link_cannot_be_used():
    ok = {"used_at": None, "revoked_at": None, "expires_at": NOW + timedelta(hours=1)}
    assert ea.link_problem(ok, NOW) is None and ea.link_problem(None, NOW) == "invalid"
    assert ea.link_problem({**ok, "used_at": NOW}, NOW) == "used" and ea.link_problem({**ok, "revoked_at": NOW}, NOW) == "revoked"
    assert ea.link_problem({**ok, "expires_at": NOW - timedelta(seconds=1)}, NOW) == "expired"
    assert ea.expires_at(NOW, 48) == NOW + timedelta(hours=48) and ea.expires_at(NOW, 0) == NOW + timedelta(hours=1)
    assert ea.action_from("approve") == "approve" and ea.action_from("delete") is None and ea.action_from(None) is None


def test_the_rate_limit_counts_per_caller_and_forgets():
    r = rate_limit.RateLimit(3, 10)
    assert [r.allow("a", t) for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert r.allow("b", 3) is True                                                   # another caller is separate
    assert r.allow("a", 11.5) is True                                                # the old hits have aged out


# ---- the flow ----

@pytest.fixture
def w(monkeypatch) -> World:
    world = standard_world(monkeypatch)
    people = {MANAGER: SimpleNamespace(user_id=MANAGER, username="mgr@x.co", display_name="Mgr", role="manager", is_active=True, email="manager@x.co")}
    monkeypatch.setattr(role_repository, "find_permissions_by_role", lambda: {"manager": {"approvals:write", "approvals:read"}, "admin": {"approvals:write"}})
    monkeypatch.setattr(user_repository, "find_user_by_id", lambda uid: people.get(str(uid)))
    monkeypatch.setattr("app.controllers.decision_controller.audit.record", lambda action, **kw: world.audit.append((action, kw)))
    world.people = people
    world.audit = []
    access.invalidate()
    return world


def big_order(w, requester="ravi@x.co"):
    case_id = w.submit("50 cameras", requester=requester)
    for name, price in (("Acme", "90,000"), ("Globex", "95,000")):
        w.reply(case_id, name, f"Total Rs {price}. Delivery 7 days. Terms: net 30")
    w.expire_quote_deadline(case_id)
    w.tick()
    assert w.stage(case_id) == "awaiting_approval"
    return case_id


def links_in(w, mark=0):
    """{'approve': token, 'refuse': token} from the plain-text part of the latest approval email to the manager."""
    mails = [m for m in w.sent[mark:] if m[0] == "manager@x.co" and "/decide/" in m[2]]
    assert mails, "the approver was not sent any buttons"
    found = {a: t for t, a in re.findall(r"/decide/([\w-]+)\?a=(approve|refuse)", mails[-1][2])}
    assert set(found) == {"approve", "refuse"} and found["approve"] == found["refuse"]                # one personal link, two buttons
    return found


def test_the_email_carries_a_personal_link_for_an_order_within_the_limit(w):
    case_id = big_order(w)
    token = links_in(w)["approve"]
    assert len(token) >= 40                                                                # long and random, not guessable
    mail = [m for m in w.sent if m[0] == "manager@x.co" and "/decide/" in m[2]][-1]
    assert "works once" in mail[2] and "expires in 48 hours" in mail[2] and "confirm" in mail[2]
    assert [l.approval_id for l in w.links] == [next(a.approval_id for a in w.approvals if a.case_id == case_id)]
    assert len(w.links) == 1 and w.links[0].token_hash != token and len(w.links[0].token_hash) == 64      # only a hash is stored


def test_no_buttons_above_the_limit_or_when_switched_off(w, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_APPROVE_MAX_AMOUNT", 50000)
    big_order(w)
    assert not [m for m in w.sent if "/decide/" in m[2]] and w.links == []
    assert any(m[0] == "manager@x.co" and "Approval needed" in m[1] for m in w.sent)       # they still get the ordinary email


def test_opening_the_link_only_shows_the_order_and_changes_nothing(w):
    case_id = big_order(w)
    token = links_in(w)["approve"]
    info = decision_controller.get_info(token)
    assert info.kind == "vendor_selection" and info.chosen.price == 90000.0 and info.recipient == "Mgr" and info.can_decide
    assert info.case_number == w.cases[case_id].case_number and any("auto-approve" in r for r in info.reasons)
    assert w.links[0].used_at is None and w.stage(case_id) == "awaiting_approval"                       # an email scanner opening it harms nothing
    decision_controller.get_info(token)                                                                # and it can be opened again


def test_one_tap_to_approve_orders_it_and_the_link_is_then_dead(w):
    case_id = big_order(w)
    token = links_in(w)["approve"]
    result = decision_controller.decide(token, "approve", None, "10.0.0.5")
    assert result.outcome == "approved" and "being sent to the supplier" in result.message
    assert w.stage(case_id) == "po_issued" and case_id in w.pos
    assert w.links[0].used_at is not None and w.links[0].used_action == "approve"
    assert w.audit[-1][0] == "approval.approve" and w.audit[-1][1]["detail"]["via"] == "email_link" and w.audit[-1][1]["actor_username"] == "mgr@x.co"
    with pytest.raises(LinkProblem) as again:
        decision_controller.decide(token, "approve", None, "10.0.0.5")
    assert again.value.key == "used"
    with pytest.raises(LinkProblem):
        decision_controller.get_info(token)


def test_one_tap_to_refuse_closes_the_request(w):
    case_id = big_order(w)
    decision_controller.decide(links_in(w)["refuse"], "refuse", "too dear", None)
    assert w.stage(case_id) == "rejected" and w.cases[case_id].status == "closed" and case_id not in w.pos


def test_a_link_stops_working_when_the_order_is_decided_in_the_app(w):
    from app.controllers import approval_controller
    case_id = big_order(w)
    token = links_in(w)["approve"]
    case_pipeline_decide = __import__("app.orchestrator.case_pipeline", fromlist=["x"]).decide_approval
    approval = next(a for a in approval_agent.get_approvals(case_id=case_id) if a["status"] == "pending")
    case_pipeline_decide(approval["approval_id"], False, "boss", "no")
    with pytest.raises(LinkProblem) as e:
        decision_controller.decide(token, "approve", None, None)
    assert e.value.key == "decided" and case_id not in w.pos


def test_a_reminder_replaces_the_earlier_link(w):
    big_order(w)
    old = links_in(w)["approve"]
    for a in w.approvals:
        a.created_at -= timedelta(days=2)
    from app.orchestrator import case_pipeline
    mark = len(w.sent)
    assert case_pipeline.remind_pending_approvals() == 1
    new = links_in(w, mark)["approve"]
    assert new != old
    with pytest.raises(LinkProblem) as e:
        decision_controller.get_info(old)
    assert e.value.key == "revoked"
    assert decision_controller.get_info(new).can_decide


def test_an_expired_link_is_refused(w):
    big_order(w)
    token = links_in(w)["approve"]
    w.links[0].expires_at = now() - timedelta(seconds=1)
    with pytest.raises(LinkProblem) as e:
        decision_controller.decide(token, "approve", None, None)
    assert e.value.key == "expired"


def test_nobody_can_approve_their_own_request_by_link(w):
    case_id = big_order(w, requester="mgr@x.co")
    token = links_in(w)["approve"]
    info = decision_controller.get_info(token)
    assert not info.can_decide and "someone else has to approve" in info.blocked
    with pytest.raises(RuleViolation):
        decision_controller.decide(token, "approve", None, None)
    assert w.links[0].used_at is None and w.stage(case_id) == "awaiting_approval"           # the link is not spent by a refusal


def test_a_person_who_can_no_longer_approve_cannot_use_their_link(w):
    big_order(w)
    token = links_in(w)["approve"]
    w.people[MANAGER].is_active = False
    with pytest.raises(LinkProblem) as e:
        decision_controller.decide(token, "approve", None, None)
    assert e.value.key == "person"
    w.people[MANAGER].is_active = True
    w.people[MANAGER].role = "viewer"                                                        # (a role without the approve permission)
    access.invalidate()
    with pytest.raises(LinkProblem):
        decision_controller.get_info(token)


def test_the_limit_is_checked_again_when_the_link_is_used(w, monkeypatch):
    big_order(w)
    token = links_in(w)["approve"]
    monkeypatch.setattr(settings, "EMAIL_APPROVE_MAX_AMOUNT", 10000)
    with pytest.raises(LinkProblem) as e:
        decision_controller.decide(token, "approve", None, None)
    assert e.value.key == "revoked" and w.links[0].used_at is None


def test_a_changed_or_made_up_token_is_just_not_valid(w):
    big_order(w)
    token = links_in(w)["approve"]
    for bad in (token[:-1] + ("A" if token[-1] != "A" else "B"), "x" * 43, "", "a" * 500):
        with pytest.raises(LinkProblem) as e:
            decision_controller.get_info(bad)
        assert e.value.key == "invalid"


def test_the_public_page_needs_no_login_says_little_and_is_rate_limited(w, monkeypatch):
    big_order(w)
    token = links_in(w)["approve"]
    r = client.get(f"/decisions/{token}")
    assert r.status_code == 200 and r.json()["chosen"]["price"] == 90000.0
    assert "email" not in r.text.lower() or "@" not in r.text                                 # no addresses in what a link holder can read
    nope = client.get("/decisions/not-a-real-token")
    assert nope.status_code == 404 and nope.json() == {"detail": "This link is not valid.", "reason": "invalid"}
    assert client.post(f"/decisions/{token}", json={"action": "delete"}).status_code == 422
    from app.api.routes import decisions
    monkeypatch.setattr(decisions, "_limit", rate_limit.RateLimit(2, 600))
    codes = [client.get("/decisions/guess").status_code for _ in range(4)]
    assert codes[:2] == [404, 404] and codes[2:] == [429, 429]


def test_it_works_the_same_over_http_and_only_once(w):
    case_id = big_order(w)
    token = links_in(w)["approve"]
    ok = client.post(f"/decisions/{token}", json={"action": "approve"})
    assert ok.status_code == 200 and ok.json()["outcome"] == "approved" and case_id in w.pos
    gone = client.post(f"/decisions/{token}", json={"action": "approve"})
    assert gone.status_code == 410 and gone.json()["reason"] in ("used", "decided", "revoked")


# ---- a supplier's higher price can be decided the same way ----

def test_a_higher_price_can_be_accepted_or_refused_from_the_email(w):
    case_id = w.submit("50 cameras")
    source(w, case_id, {"Acme": QUOTE_42K, "Globex": QUOTE_45K})
    assert w.stage(case_id) == "po_issued"
    mark = len(w.sent)
    w.reply(case_id, w.pos[case_id].vendor_name, "Steel went up, the price is now Rs 55,000.", subject=f"RE: [OA-{case_id}] Purchase Order PO-1001")
    token = links_in(w, mark)["approve"]
    info = decision_controller.get_info(token)
    assert info.kind == "price_change" and info.price_change.new_total == 55000.0 and info.price_change.agreed_total == 42000.0
    decision_controller.decide(token, "approve", None, None)
    assert w.pos[case_id].total_amount == 55000.0 and w.stage(case_id) == "po_issued"
