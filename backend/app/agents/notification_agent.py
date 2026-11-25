"""
Tells humans when the system needs them. Emails every active manager and admin
that has an email address. Logs the outcome on the case so it is auditable.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.agents import approval_link_agent, operations_agent
from app.clients import email_client
from app.core import access, email_approval
from app.core.approver_leave import effective_approvers, on_leave
from app.core.config import settings
from app.repositories import user_repository

logger = logging.getLogger(__name__)

# Alerts go to the people who can act on them (each department holds its own permission), and to admins,
# rather than to a job title. If a department has nobody, the admins are told instead.
from app.core.permissions import ALERT_FALLBACK_PERMISSION, ALERT_PERMISSION

RECIPIENT_PERMISSION = ALERT_PERMISSION["approval"]


def notify_approval_needed(case_id: str, vendor_name: str, rationale: str | None,
                           reasons: list[str], reminder: bool = False, approval_id: str | None = None,
                           amount: float | None = None, kind: str = "vendor_selection", summary: str | None = None,
                           review: dict | None = None) -> None:
    """Tell the approvers. With `approval_id` and an `amount` within the email-approval limit, each approver gets their own
    one-tap Approve / Refuse links; otherwise the email just points to the app."""
    reason_lines = "\n".join(f"  - {r}" for r in reasons)
    prefix = "REMINDER - still waiting: " if reminder else ""
    label = (review or {}).get("case_number") or case_id[:8]
    body = (
        f"A vendor selection needs your approval.\n\n"
        f"Case: {label}\n"
        f"Recommended vendor: {vendor_name}\n"
        f"Why the AI picked them: {rationale or 'n/a'}\n\n"
        f"Why a human is needed:\n{reason_lines}\n\n"
        f"{_details_text(review)}"
        f"Review and approve or reject here: {settings.APP_BASE_URL}\n"
    )
    subject = f"{prefix}Approval needed - {label}"
    kind_name = "approval_reminder" if reminder else "approval_requested"
    if approval_id and email_approval.offer_link(settings.EMAIL_APPROVE_ENABLED, amount, settings.EMAIL_APPROVE_MAX_AMOUNT, kind):
        _notify_with_links(case_id, kind_name, subject, body, approval_id, vendor_name, amount, reasons, summary, kind, review)
        return
    _notify(case_id, kind_name, subject, body)


def _notify_with_links(case_id: str, kind_name: str, subject: str, body: str, approval_id: str, vendor_name: str,
                       amount: float | None, reasons: list[str], summary: str | None, kind: str, review: dict | None = None) -> None:
    people = _recipient_users("approval")
    if not people:
        _notify(case_id, kind_name, subject, body)               # nobody to give a personal link to: the usual route (and its "nobody" alert)
        return
    sent = failed = 0
    for person in people:
        try:
            token = approval_link_agent.create_link(approval_id, str(person.user_id))
            base = f"{settings.APP_BASE_URL}/decide/{token}"
            plain = (f"{body}\n--- Decide from this email (one tap, works once, for you only) ---\n"
                     f"Approve: {base}?a=approve\nRefuse:  {base}?a=refuse\n"
                     f"The link opens a page where you confirm. It expires in {settings.EMAIL_APPROVE_HOURS:g} hours.\n")
            email_client.send_email(person.email, subject, plain, html=_approval_html(case_id, vendor_name, amount, reasons, summary, base, kind, review))
            sent += 1
        except Exception:
            logger.exception("Approval email with links to %s failed", person.email)
            failed += 1
    operations_agent.publish_event(
        case_id, "notification.sent", agent_name="Notification Agent",
        payload={"kind": kind_name, "team": "approval", "sent": sent, "failed": failed, "one_tap": True},
    )


def _approval_html(case_id: str, vendor_name: str, amount: float | None, reasons: list[str], summary: str | None, base: str, kind: str,
                   review: dict | None = None) -> str:
    from html import escape
    what = "A supplier asks for a higher price" if kind == "price_change" else "An order needs your approval"
    rows = "".join(f"<li style='margin:2px 0'>{escape(r)}</li>" for r in reasons)
    money = f"<p style='margin:8px 0;font-size:20px'><b>₹{amount:,.0f}</b> · {escape(vendor_name)}</p>" if amount is not None else f"<p style='margin:8px 0'><b>{escape(vendor_name)}</b></p>"
    button = "display:inline-block;padding:12px 22px;border-radius:10px;font-weight:600;text-decoration:none;margin-right:10px;"
    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:640px;color:#222'>"
        f"<h2 style='margin:0 0 6px'>{what}</h2>"
        f"{money}{('<p style=margin:6px 0;color:#555>' + escape(summary) + '</p>') if summary else ''}"
        f"<p style='margin:10px 0 4px'><b>Why a person is needed</b></p><ul style='margin:0 0 14px;padding-left:18px'>{rows}</ul>"
        f"{_details_html(review)}"
        f"<p style='margin:14px 0'><a href='{base}?a=approve' style='{button}background:#16a34a;color:#fff'>Approve</a>"
        f"<a href='{base}?a=refuse' style='{button}background:#fff;color:#c53536;border:1px solid #c53536'>Refuse</a></p>"
        f"<p style='font-size:12px;color:#777'>The button opens a page where you confirm. It works once, only for you, and expires in "
        f"{settings.EMAIL_APPROVE_HOURS:g} hours. To choose a different supplier, open the app: {escape(settings.APP_BASE_URL)}</p></div>"
    )


def _rs(v) -> str:
    return f"Rs {v:,.0f}" if isinstance(v, (int, float)) else "n/a"


def _details_text(review: dict | None) -> str:
    """The full picture as plain text: who asked for what, by when, and every supplier's offer."""
    if not review:
        return ""
    out = ["--- Full details ---"]
    if review.get("requested_by"):
        out.append(f"Requested by: {review['requested_by']}")
    if review.get("request_text"):
        out.append(f"Request: {review['request_text']}")
    items = review.get("items") or []
    if items:
        out.append("Items: " + ", ".join(f"{i['description']} x {i['quantity']}" for i in items))
    if review.get("urgent") or review.get("needed_by"):
        out.append(("URGENT. " if review.get("urgent") else "") + (f"Needed by {review['needed_by']}" if review.get("needed_by") else ""))
    pc = review.get("price_change")
    if pc:
        out.append(f"Price change on {pc.get('po_number')} ({pc.get('vendor_name')}): agreed {_rs(pc.get('agreed_total'))}, "
                   f"now asking {_rs(pc.get('new_total'))}" + (f" (+{pc['pct']}%)" if pc.get("pct") is not None else ""))
        if pc.get("reply_text"):
            out.append(f"Supplier wrote: {pc['reply_text']}")
    options = review.get("options") or []
    if options:
        out.append("\nSupplier offers:")
        for o in options:
            line = f"  {o.get('rank') or '-'}. {o['vendor_name']}: {_rs(o.get('price'))}"
            if o.get("lead_time_days") is not None:
                line += f", {o['lead_time_days']} days"
            if o.get("terms"):
                line += f", {o['terms']}"
            if o.get("reliability") is not None:
                line += f", reliability {o['reliability']}"
            if o.get("tags"):
                line += f" [{', '.join(o['tags'])}]"
            out.append(line)
            if o.get("reason"):
                out.append(f"       AI: {o['reason']}")
    if (review.get("negotiation") or {}).get("text"):
        out.append(f"\nNegotiation: {review['negotiation']['text']}")
    if review.get("suggestion"):
        out.append(f"\nSuggestion: {review['suggestion']}")
    return "\n".join(out) + "\n\n"


def _details_html(review: dict | None) -> str:
    from html import escape
    if not review:
        return ""
    cell = "padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top;"
    facts = []
    if review.get("requested_by"):
        facts.append(("Requested by", escape(str(review["requested_by"]))))
    if review.get("request_text"):
        facts.append(("Request", escape(review["request_text"])))
    items = review.get("items") or []
    if items:
        facts.append(("Items", ", ".join(f"{escape(i['description'])} × {i['quantity']}" for i in items)))
    if review.get("urgent") or review.get("needed_by"):
        facts.append(("Timing", ("<b style='color:#c53536'>URGENT</b> " if review.get("urgent") else "") + (f"needed by {review['needed_by']}" if review.get("needed_by") else "")))
    pc = review.get("price_change")
    if pc:
        facts.append(("Price change", f"{escape(str(pc.get('po_number')))} · {escape(str(pc.get('vendor_name')))}: agreed {_rs(pc.get('agreed_total'))}, "
                                      f"now asking <b>{_rs(pc.get('new_total'))}</b>" + (f" (+{pc['pct']}%)" if pc.get("pct") is not None else "")))
        if pc.get("reply_text"):
            facts.append(("Supplier wrote", escape(pc["reply_text"])))
    top = "".join(f"<tr><td style='{cell}color:#777;white-space:nowrap'>{k}</td><td style='{cell}'>{v}</td></tr>" for k, v in facts)
    out = f"<p style='margin:14px 0 4px'><b>Order details</b></p><table style='border-collapse:collapse;width:100%;font-size:14px'>{top}</table>" if top else ""
    options = review.get("options") or []
    if options:
        rows = ""
        for o in options:
            tags = "".join(f"<span style='background:#fdecec;color:#c53536;border-radius:8px;padding:1px 6px;font-size:11px;margin-right:4px'>{escape(t)}</span>" for t in o.get("tags") or [])
            why = f"<div style='color:#666;font-size:12px;margin-top:3px'>{escape(o['reason'])}</div>" if o.get("reason") else ""
            terms = ", ".join(x for x in [f"{o['lead_time_days']} days" if o.get("lead_time_days") is not None else "", o.get("terms") or ""] if x)
            rel = f"{o['reliability']}" if o.get("reliability") is not None else "–"
            rows += (f"<tr><td style='{cell}'>{o.get('rank') or '–'}</td><td style='{cell}'><b>{escape(o['vendor_name'])}</b> {tags}{why}</td>"
                     f"<td style='{cell}white-space:nowrap'><b>{_rs(o.get('price'))}</b></td><td style='{cell}'>{escape(terms)}</td><td style='{cell}'>{rel}</td></tr>")
        out += (f"<p style='margin:14px 0 4px'><b>Supplier offers</b></p><table style='border-collapse:collapse;width:100%;font-size:13px'>"
                f"<tr style='text-align:left;color:#777'><th style='{cell}'>#</th><th style='{cell}'>Supplier</th><th style='{cell}'>Price</th><th style='{cell}'>Delivery · terms</th><th style='{cell}'>Reliability</th></tr>{rows}</table>")
    if (review.get("negotiation") or {}).get("text"):
        out += f"<p style='margin:12px 0;padding:10px 12px;background:#ecfdf5;border-radius:8px;font-size:13px'><b>Negotiation:</b> {escape(review['negotiation']['text'])}</p>"
    if review.get("suggestion"):
        out += f"<p style='margin:12px 0;padding:10px 12px;background:#f7f7fa;border-radius:8px;font-size:13px'>{escape(review['suggestion'])}</p>"
    return out


def _person(row) -> dict:
    role = getattr(row, "role", None)
    return {"user_id": str(getattr(row, "user_id", "") or ""), "username": getattr(row, "username", None) or getattr(row, "email", ""), "email": getattr(row, "email", None), "role": role, "active": bool(getattr(row, "is_active", True)),
            "can_approve": role == "admin" or access.has_permission(role, RECIPIENT_PERMISSION) if role else True,
            "on_leave_from": getattr(row, "on_leave_from", None), "on_leave_until": getattr(row, "on_leave_until", None),
            "delegate_user_id": str(row.delegate_user_id) if getattr(row, "delegate_user_id", None) else None}


def today_india():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


def _directory() -> tuple[dict, dict]:
    """({user_id: person}, {user_id: row}) of every user, for finding a delegate. Empty when it cannot be read."""
    try:
        rows = list(user_repository.find_all_users())
    except Exception:
        logger.exception("Could not read the users to find a delegate")
        return {}, {}
    return {str(r.user_id).lower(): _person(r) for r in rows}, {str(r.user_id).lower(): r for r in rows}


def approver_cover_inputs() -> tuple[list[dict], dict, object]:
    """(approvers, directory, today) for core/agent_cases.approver_cover: everyone who may approve (admins included), every user (to find a
    delegate), and today in India."""
    people = approver_people()
    directory = _directory()[0] if any(on_leave(p, today_india()) for p in people) else {}
    return people, directory, today_india()


def _leave_aware(rows: list) -> list:
    """The approvers to e-mail today: someone on leave is replaced by their delegate. Costs nothing when nobody is on leave."""
    today = today_india()
    people = [_person(r) for r in rows]
    if not any(on_leave(p, today) for p in people):
        return rows
    directory, row_of = _directory()
    effective = effective_approvers(people, directory, today)
    chosen = [row_of.get(p["user_id"].lower()) or next((r for r in rows if str(r.user_id) == p["user_id"]), None) for p in effective["askable"]]
    return [r for r in chosen if r is not None]


def approver_people() -> list[dict]:
    """Every active user who may approve orders, as plain dicts (admins included). Unlike the recipient lists this does NOT fall back to
    the admins when there is nobody: the pipeline needs to know the truth in order to say so."""
    return [_person(u) for u in user_repository.find_active_users_with_permission(RECIPIENT_PERMISSION)]


def _recipient_users(team: str | None) -> list:
    asked = ALERT_PERMISSION.get(team or "", RECIPIENT_PERMISSION if team == "approval" else ALERT_FALLBACK_PERMISSION)
    people = list(user_repository.find_active_users_with_permission(asked))
    if team == "approval":
        people = _leave_aware(people)
    return people or list(user_repository.find_active_users_with_permission(ALERT_FALLBACK_PERMISSION))


def notify_unmatched_document(from_email: str, vendor_name: str | None, subject: str, files: list[str]) -> None:
    """A supplier sent a document that belongs to no order we can find. There is no case yet, so this is a plain email to Accounts
    (or the admins if nobody holds that role), pointing to the Unmatched documents page."""
    who = f"{vendor_name} <{from_email}>" if vendor_name else from_email
    body = (
        f"{who} sent a document that the system could not match to any order.\n\n"
        f"Subject: {subject or '(none)'}\n"
        f"Files: {', '.join(files) if files else 'none (the text of the email)'}\n\n"
        f"Please open Unmatched documents and attach it to the right case (or dismiss it):\n{settings.APP_BASE_URL}/documents\n"
    )
    for address in _recipients("invoice"):
        try:
            email_client.send_email(address, "A supplier document needs a case", body)
        except Exception:
            logger.exception("Could not tell %s about an unmatched document", address)


def notify_case_stalled(case_id: str, reason: str, team: str | None = None) -> None:
    """`team` is the department to ask (vendor, po, delivery, invoice); None means the admins."""
    body = (
        f"A case could not move forward on its own and needs a person.\n\n"
        f"Case: {case_id}\n"
        f"Reason: {reason}\n\n"
        f"Open the case here: {settings.APP_BASE_URL}\n"
    )
    _notify(case_id, "case_stalled", f"Case stalled - {case_id[:8]}", body, team)


def notify_escalation(case_id: str, headline: str, hours_waiting: float, label: str | None = None) -> None:
    """Nobody has dealt with this for a long time: tell the admins, whoever it was first sent to."""
    body = (
        f"{headline}, and it has been waiting about {hours_waiting:g} hours with nobody acting on it.\n\n"
        f"Case: {label or case_id}\n\n"
        f"Please see that the right person picks it up, or deal with it yourself:\n{settings.APP_BASE_URL}\n"
    )
    _notify(case_id, "escalation", f"ESCALATED after {hours_waiting:g}h - {headline}", body, team=None)


def _recipients(team: str | None) -> list[str]:
    asked = ALERT_PERMISSION.get(team or "", RECIPIENT_PERMISSION if team == "approval" else ALERT_FALLBACK_PERMISSION)
    rows = list(user_repository.find_active_users_with_permission(asked))
    people = [u.email for u in (_leave_aware(rows) if team == "approval" else rows)]
    return people or [u.email for u in user_repository.find_active_users_with_permission(ALERT_FALLBACK_PERMISSION)]


def _notify(case_id: str, kind: str, subject: str, body: str, team: str | None = "approval") -> None:
    recipients = _recipients(team)
    if not recipients:
        logger.warning("Nobody who can approve has an email address; '%s' for case %s not sent", kind, case_id)
        operations_agent.publish_event(
            case_id, "notification.no_recipients", agent_name="Notification Agent",
            payload={"kind": kind, "team": team},
        )
        return

    sent, failed = 0, 0
    for address in recipients:
        try:
            email_client.send_email(address, subject, body)
            sent += 1
        except Exception:
            logger.exception("Notification '%s' to %s failed", kind, address)
            failed += 1

    operations_agent.publish_event(
        case_id, "notification.sent", agent_name="Notification Agent",
        payload={"kind": kind, "team": team, "sent": sent, "failed": failed},
    )


def notify_system(kind: str, label: str, detail: str, since_text: str) -> int:
    """Tell the admins that one of the system's own background jobs has stopped ("down") or is working again
    ("recovered"). Not about any one case, so nothing is written to a case timeline. Returns how many were emailed."""
    if kind == "recovered":
        subject = f"Recovered: {label} is working again"
        body = f"{label} is working again.\n\nIt had been having a problem since {since_text}.\n\nNothing more is needed.\n"
    elif kind == "restarted":
        subject = f"Restarted: {label} had stopped and was started again"
        body = (f"{label} had stopped, so the app started it again by itself.\n\nWhat was seen: {detail}\nSince: {since_text}\n\n"
                f"Nothing is needed unless you get another message that it keeps stopping. You will not be emailed for each restart.\n{settings.APP_BASE_URL}\n")
    elif kind == "gave_up":
        subject = f"ALERT: {label} keeps stopping"
        body = (f"{label} stopped again and again, and the app has used up the restarts it may do this hour.\n\nWhat was seen: {detail}\nSince: {since_text}\n\n"
                f"What to do: restart the Operation Agents server. If it comes straight back to this state, check the System Health tab in Settings and the server log.\n{settings.APP_BASE_URL}\n")
    else:
        subject = f"ALERT: {label} needs attention"
        body = (
            f"{label} has stopped doing its job, so some things will not happen on their own until it is fixed.\n\n"
            f"What was seen: {detail}\n"
            f"Since: {since_text}\n\n"
            f"What to do: restart the Operation Agents server. If it comes straight back to this state, check the "
            f"System Health tab in Settings and the server log.\n{settings.APP_BASE_URL}\n"
        )
    recipients = [a for a in _recipients(None) if a]
    sent = 0
    for address in recipients:
        try:
            email_client.send_email(address, subject, body)
            sent += 1
        except Exception:
            logger.exception("System alert to %s failed", address)
    if not recipients:
        logger.warning("Nobody with an email address can be told: %s (%s)", subject, detail)
    return sent
