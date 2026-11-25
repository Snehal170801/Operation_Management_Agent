"""An in-memory stand-in for the database, email and AI, so the REAL agents and pipeline can be
run end to end in tests. Only the edges are faked (repositories, email_client, the AI call);
every agent, policy and pipeline function in between is the production code."""

import ast
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.agents import (
    approval_agent,
    delivery_agent,
    invoice_agent,
    operations_agent,
    purchase_agent,
    purchase_order_agent,
    vendor_agent,
)
from app.clients import azure_openai_client, email_client
from app.core import stock_ledger
from app.orchestrator import case_pipeline, worker
from app.repositories import (
    approval_link_repository,
    approval_repository,
    case_repository,
    goods_issue_repository,
    invoice_repository,
    purchase_order_repository,
    purchase_repository,
    read_file_repository,
    rfq_repository,
    stock_repository,
    unmatched_document_repository,
    user_repository,
    vendor_repository,
)

# Silence "imported but unused": these modules are listed so a typo in the import list fails loudly.
_ = (approval_agent, delivery_agent, invoice_agent, operations_agent, purchase_agent,
     purchase_order_agent, vendor_agent)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def row(**fields) -> SimpleNamespace:
    return SimpleNamespace(**fields)


class World:
    def __init__(self):
        self.cases: dict[str, SimpleNamespace] = {}
        self.events: dict[str, list] = {}
        self.requests: dict[str, SimpleNamespace] = {}      # case_id -> purchase request row
        self.items: dict[str, list] = {}                    # purchase_request_id -> item rows
        self.stock: dict[str, SimpleNamespace] = {}
        self.ledger: list[SimpleNamespace] = []             # the stock history, oldest first
        self.vendors: dict[str, SimpleNamespace] = {}
        self.quotes: list = []
        self.selections: dict[str, SimpleNamespace] = {}
        self.rfqs: list = []
        self.approvals: list = []
        self.documents: list[SimpleNamespace] = []          # documents no order was found for
        self.read_file_names: dict[tuple, str] = {}
        self.read_files: dict[str, set[str]] = {}           # case_id -> fingerprints of the attachments already read
        self.pos: dict[str, SimpleNamespace] = {}            # case_id -> PO row
        self.invoices: list = []
        self.issues: list = []
        self.links: list = []
        self.managers = ["manager@x.co"]
        self.sent: list[tuple[str, str, str]] = []           # every email: (to, subject, body)
        self.inbox: list[dict] = []
        self.parsed_requests: dict[str, dict] = {}
        self.stock_ai: dict[str, str | None] = {}   # what the stock-matching AI answers
        self._po_seq = 1000
        self._event_seq = 0

    # ---------- setup helpers ----------
    def add_vendor(self, name, reliability=4.5, email="auto"):
        vid = str(uuid.uuid4())
        self.vendors[vid] = row(vendor_id=vid, name=name, reliability_score=reliability, created_at=now(), email_bounced_at=None, email_bounce_reason=None,
                                email=f"{name.lower()}@vendor.com" if email == "auto" else email)
        return vid

    def add_stock(self, description, quantity, min_level=None, target_level=None, unit=None, category=None, preferred_vendor_id=None):
        self.stock[description.lower()] = row(stock_id=str(uuid.uuid4()), item_description=description, quantity_available=quantity,
                                              updated_at=now(), min_level=min_level, target_level=target_level,
                                              unit=unit, category=category, preferred_vendor_id=preferred_vendor_id)

    def teach(self, raw_request, items, **extra):
        """`extra` is anything else the AI reads out of the text, e.g. needed_by="2026-10-09" or urgent=True."""
        self.parsed_requests[raw_request] = {"items": items, "cost_center": None, **extra}

    def vendor_id(self, name):
        return next(v.vendor_id for v in self.vendors.values() if v.name == name)

    # ---------- driving the system ----------
    def submit(self, raw_request, requester="ravi@x.co"):
        return case_pipeline.start_case(requester, raw_request)

    def reply(self, case_id, vendor_name, body, subject=None, attachments=None, tagged=True):
        """A vendor emails back; the mailbox reader hands it to the pipeline. `tagged=False` is a fresh email with no case tag."""
        vendor = self.vendors[self.vendor_id(vendor_name)]
        return case_pipeline.ingest_quote_email({
            "from_email": vendor.email,
            "subject": subject if subject is not None else (f"RE: [OA-{case_id}] Request for quotation" if tagged else "Our document"),
            "body": body,
            **({"attachments": attachments} if attachments is not None else {}),
        })

    def tick(self):
        """One background-worker pass."""
        worker.run_once()

    def expire_quote_deadline(self, case_id):
        for r in self.rfqs:
            if r.case_id == case_id:
                r.deadline_at = now() - timedelta(hours=1)

    def stage(self, case_id):
        return self.cases[case_id].stage

    def event_types(self, case_id):
        return [e.event_type for e in self.events.get(case_id, [])]

    def emails_to(self, address):
        return [m for m in self.sent if m[0] == address]

    # ---------- install ----------
    def install(self, monkeypatch):
        w = self

        def patch(module, **fns):
            for name, fn in fns.items():
                monkeypatch.setattr(module, name, fn)

        # ---- cases & events
        def insert_case(case_id, requester_id):
            w.cases[case_id] = row(case_id=case_id, case_number=f"REQ-2026-{len(w.cases) + 1:04d}", requester_id=requester_id, stage="created", status="open",
                                   summary=None, created_at=now(), updated_at=now())

        def touch(case_id, **kw):
            c = w.cases[case_id]
            for k, v in kw.items():
                setattr(c, k, v)
            c.updated_at = now()

        def insert_event(case_id, event_type, agent_name=None, payload=None):
            w._event_seq += 1
            w.events.setdefault(case_id, []).append(
                row(event_id=w._event_seq, event_type=event_type, agent_name=agent_name,
                    payload=payload or {}, created_at=now()))

        def find_open_case_ids_by_stage(stage, idle_since=None):
            return [c.case_id for c in w.cases.values() if c.stage == stage and c.status == "open"
                    and (idle_since is None or c.updated_at <= idle_since)]

        def find_all_cases(requester_id=None):
            rows = []
            for c in w.cases.values():
                if requester_id and c.requester_id.lower() != requester_id.lower():
                    continue
                req = w.requests.get(c.case_id)
                items = w.items.get(req.purchase_request_id, []) if req else []
                rows.append(row(case_id=c.case_id, case_number=c.case_number, requester_id=c.requester_id, stage=c.stage, status=c.status,
                                created_at=c.created_at, updated_at=c.updated_at, item_count=len(items), total_quantity=sum(i.quantity for i in items),
                                items_summary=", ".join(f"{i.description} ({i.quantity})" for i in items),
                                urgent=1 if req and req.urgent else 0, needed_by=req.needed_by if req else None))
            return rows

        def events_of_types(types, since=None):
            found = [{"case_id": cid, "event_type": e.event_type, "payload": e.payload, "created_at": e.created_at}
                     for cid, events in w.events.items() for e in events if e.event_type in types and (since is None or e.created_at >= since)]
            return sorted(found, key=lambda e: e["created_at"])

        monkeypatch.setattr(operations_agent, "get_events_of_types", events_of_types)

        patch(case_repository,
              find_all_cases=find_all_cases,
              insert_case=insert_case,
              find_case_by_id=lambda cid: w.cases.get(cid),
              update_case_stage=lambda cid, stage: touch(cid, stage=stage),
              update_case_stage_and_status=lambda cid, stage, status: touch(cid, stage=stage, status=status),
              insert_event=insert_event,
              find_events_by_case_id=lambda cid: list(w.events.get(cid, [])),
              find_open_case_ids_by_stage=find_open_case_ids_by_stage,
              count_cases_since=lambda requester, since: 0)

        # ---- purchase requests & stock
        def insert_purchase_request(purchase_request_id, case_id, cost_center, raw_request, needed_by=None, urgent=False):
            w.requests[case_id] = row(purchase_request_id=purchase_request_id, case_id=case_id,
                                      cost_center=cost_center, raw_request=raw_request, created_at=now(), needed_by=needed_by, urgent=urgent)

        def insert_items(purchase_request_id, items):
            w.items.setdefault(purchase_request_id, []).extend(
                row(item_id=str(uuid.uuid4()), description=i["description"], quantity=i["quantity"]) for i in items)

        def update_request_terms(purchase_request_id, needed_by, urgent):
            for r in w.requests.values():
                if r.purchase_request_id == purchase_request_id:
                    r.needed_by, r.urgent = needed_by, bool(urgent)

        def update_item_quantity(prid, description, quantity):
            for i in w.items.get(prid, []):
                if i.description == description:
                    i.quantity = quantity

        def mark_rfqs_withdrawn(case_id):
            for r in w.rfqs:
                if r.case_id == case_id:
                    r.status = "withdrawn"

        def record_ledger(item, before, after, reason, actor, case_id, note):
            entry = stock_ledger.entry_for(before, after, reason, actor, case_id, note)
            if entry:
                w.ledger.append(row(entry_id=str(uuid.uuid4()), item_description=item.item_description, created_at=now(),
                                    **{k: entry[k] for k in ("old_quantity", "new_quantity", "reason", "actor", "case_id", "note")}))

        def adjust_quantity(description, delta, *, actor, reason, case_id=None, note=None):
            item = w.stock.get(description.lower())
            if item is None:
                return None
            before = item.quantity_available
            after, clamp = stock_ledger.clamp_after(before, delta)
            item.quantity_available, item.updated_at = after, now()
            record_ledger(item, before, after, reason, actor, case_id, " ".join(filter(None, [note, clamp])))
            return before, after

        def deduct_stock(description, quantity, *, actor="Procurement Agent", reason="fulfilled_from_stock", case_id=None, note=None):
            adjust_quantity(description, -quantity, actor=actor, reason=reason, case_id=case_id, note=note)

        def upsert_stock(description, quantity, *, actor="system", reason="manual", case_id=None, note=None):
            item = w.stock.get(description.lower())
            if item is None:
                w.add_stock(description, quantity)
                record_ledger(w.stock[description.lower()], None, quantity, reason, actor, case_id, note)
            else:
                before = item.quantity_available
                item.quantity_available, item.updated_at = quantity, now()
                record_ledger(item, before, quantity, reason, actor, case_id, note)

        def update_item(description, *, new_name, unit, category, preferred_vendor_id):
            item = w.stock.pop(description.lower(), None)
            if item is None:
                return False
            item.item_description, item.unit, item.category, item.preferred_vendor_id = new_name, unit, category, preferred_vendor_id
            w.stock[new_name.lower()] = item
            for r in w.ledger:                                      # the history follows a new name
                if r.item_description.lower() == description.lower():
                    r.item_description = new_name
            return True

        def delete_item(description, actor):
            item = w.stock.pop(description.lower(), None)
            if item is None:
                return None
            entry = stock_ledger.removal_entry(item.quantity_available, actor)
            w.ledger.append(row(entry_id=str(uuid.uuid4()), item_description=item.item_description, created_at=now(),
                                **{k: entry[k] for k in ("old_quantity", "new_quantity", "reason", "actor", "case_id", "note")}))
            return item.quantity_available

        def find_ledger(description, limit=200):
            return [r for r in reversed(w.ledger) if r.item_description.lower() == description.lower()][:limit]

        patch(purchase_repository,
              update_request_terms=update_request_terms,
              update_item_quantity=update_item_quantity,
              insert_purchase_request=insert_purchase_request,
              insert_purchase_request_items=insert_items,
              find_purchase_request_by_case_id=lambda cid: w.requests.get(cid),
              find_items_by_purchase_request_id=lambda prid: w.items.get(prid, []))
        def set_levels(description, min_level, target_level):
            item = w.stock.get(description.lower())
            if item is None:
                return False
            item.min_level, item.target_level = min_level, target_level
            return True

        def add_quantity(description, quantity, *, actor="Procurement Agent", reason="restock_received", case_id=None, note=None):
            result = adjust_quantity(description, quantity, actor=actor, reason=reason, case_id=case_id, note=note)
            return None if result is None else result[1]

        patch(stock_repository,
              set_levels=set_levels,
              add_quantity=add_quantity,
              adjust_quantity=adjust_quantity,
              upsert_stock=upsert_stock,
              find_ledger=find_ledger,
              update_item=update_item,
              delete_item=delete_item,
              find_stock_by_description=lambda d: w.stock.get(d.lower()),
              deduct_stock=deduct_stock,
              find_all_stock=lambda: list(w.stock.values()))

        # ---- vendors, quotes, rfqs
        def insert_quote(quote_id, case_id, vendor_id, raw_quote_text, price, lead_time_days, terms, valid_until=None):
            w.quotes.append(row(quote_id=quote_id, case_id=case_id, vendor_id=vendor_id,
                                vendor_name=w.vendors[vendor_id].name, raw_quote_text=raw_quote_text,
                                price=price, lead_time_days=lead_time_days, terms=terms, created_at=now(), superseded_at=None, valid_until=valid_until))

        def upsert_selection(case_id, vendor_id, rationale):
            w.selections[case_id] = row(case_id=case_id, vendor_id=vendor_id,
                                        vendor_name=w.vendors[vendor_id].name, rationale=rationale,
                                        created_at=now())

        def insert_rfq(rfq_id, case_id, vendor_id, deadline_at):
            v = w.vendors[vendor_id]
            w.rfqs.append(row(rfq_id=rfq_id, case_id=case_id, vendor_id=vendor_id, vendor_name=v.name,
                              vendor_email=v.email, status="sent", sent_at=now(), last_contacted_at=now(),
                              reminder_count=0, deadline_at=deadline_at, replied_at=None))

        def mark_replied(case_id, vendor_id):
            for r in w.rfqs:
                if r.case_id == case_id and r.vendor_id == vendor_id:
                    r.status, r.replied_at = "replied", now()

        def mark_rfq_reminded(rfq_id):
            for r in w.rfqs:
                if r.rfq_id == rfq_id:
                    r.reminder_count += 1
                    r.last_contacted_at = now()

        def supersede_quotes(case_id):
            for q in w.quotes:
                if q.case_id == case_id and q.superseded_at is None:
                    q.superseded_at = now()

        def supersede_vendor_quotes(case_id, vendor_id):
            for q in w.quotes:
                if q.case_id == case_id and q.vendor_id == vendor_id and q.superseded_at is None:
                    q.superseded_at = now()

        def reopen_rfq(rfq_id, deadline_at):
            for r in w.rfqs:
                if r.rfq_id == rfq_id:
                    r.status, r.sent_at, r.last_contacted_at, r.reminder_count, r.deadline_at, r.replied_at = "sent", now(), now(), 0, deadline_at, None

        def delete_rfq(case_id, vendor_id):
            w.rfqs[:] = [r for r in w.rfqs if not (r.case_id == case_id and r.vendor_id == vendor_id)]

        def vendor_id_by_email(case_id, email):
            return next((r.vendor_id for r in w.rfqs
                         if r.case_id == case_id and (r.vendor_email or "").lower() == email.lower()), None)

        def mark_bounced_vendor(vendor_id, reason):
            w.vendors[vendor_id].email_bounced_at, w.vendors[vendor_id].email_bounce_reason = now(), reason

        def mark_rfq_bounced(case_id, vendor_id):
            for r in w.rfqs:
                if r.case_id == case_id and r.vendor_id == vendor_id and r.status == "sent":
                    r.status = "bounced"

        def rfq_cases_for_vendor(vendor_id):
            ids = {r.case_id for r in w.rfqs if r.vendor_id == vendor_id and r.status == "sent" and w.cases[r.case_id].status == "open"}
            return list(ids | {p.case_id for p in w.pos.values() if p.vendor_id == vendor_id and p.status == "sent" and w.cases[p.case_id].status == "open"})

        patch(rfq_repository, mark_bounced=mark_rfq_bounced, find_open_case_ids_for_vendor=rfq_cases_for_vendor)
        def update_vendor(vendor_id, name, email, phone, call_language, reliability_score):
            v = w.vendors.get(vendor_id)
            if v is None:
                return False
            if (email or "").lower() != (v.email or "").lower():
                v.email_bounced_at = v.email_bounce_reason = None
            v.name, v.email, v.phone, v.call_language, v.reliability_score = name, email, phone, call_language, reliability_score
            return True

        patch(vendor_repository,
              update_vendor=update_vendor,
              find_vendor_by_email=lambda e: next((v for v in w.vendors.values() if (v.email or "").lower() == e.lower()), None),
              mark_email_bounced=mark_bounced_vendor,
              find_all_vendors=lambda: sorted(w.vendors.values(), key=lambda v: v.name),
              insert_quote=insert_quote,
              find_all_quotes=lambda limit=5000: sorted((q for q in w.quotes if q.superseded_at is None), key=lambda q: q.created_at, reverse=True),
              find_quotes_by_case_id=lambda cid, include_superseded=False: [q for q in w.quotes if q.case_id == cid and (include_superseded or q.superseded_at is None)],
              supersede_quotes=supersede_quotes,
              supersede_vendor_quotes=supersede_vendor_quotes,
              delete_vendor_selection=lambda cid: w.selections.pop(cid, None),
              upsert_vendor_selection=upsert_selection,
              find_vendor_selection_by_case_id=lambda cid: w.selections.get(cid))
        patch(rfq_repository,
              insert_rfq=insert_rfq,
              mark_withdrawn=mark_rfqs_withdrawn,
              reopen=reopen_rfq,
              delete_rfq=delete_rfq,
              find_rfqs_by_case_id=lambda cid: [r for r in w.rfqs if r.case_id == cid],
              mark_replied=mark_replied,
              mark_reminded=mark_rfq_reminded,
              find_vendor_id_by_email=vendor_id_by_email)

        # ---- approvals
        def insert_approval(approval_id, case_id, approval_type, status, reasons, decided_by=None):
            w.approvals.append(row(approval_id=approval_id, case_id=case_id, approval_type=approval_type,
                                   status=status, reasons=json.dumps(reasons), decided_by=decided_by,
                                   decision_note=None, created_at=now(), reminder_count=0,
                                   last_reminded_at=None,
                                   decided_at=None if status == "pending" else now()))

        def supersede_pending(case_id, approval_type):
            for a in w.approvals:
                if a.case_id == case_id and a.approval_type == approval_type and a.status == "pending":
                    a.status = "superseded"

        def decide_pending(approval_id, status, decided_by, note):
            for a in w.approvals:
                if a.approval_id == approval_id and a.status == "pending":
                    a.status, a.decided_by, a.decision_note, a.decided_at = status, decided_by, note, now()
                    return True
            return False

        def due_for_reminder(cutoff, max_reminders):
            return [a for a in w.approvals if a.status == "pending" and a.reminder_count < max_reminders
                    and (a.last_reminded_at or a.created_at) <= cutoff]

        def mark_approval_reminded(approval_id):
            for a in w.approvals:
                if a.approval_id == approval_id:
                    a.reminder_count += 1
                    a.last_reminded_at = now()

        patch(approval_repository,
              insert_approval=insert_approval,
              supersede_pending=supersede_pending,
              find_approval_by_id=lambda aid: next((a for a in w.approvals if a.approval_id == aid), None),
              find_approvals=lambda status=None, case_id=None: list(reversed([       # newest first, like the database
                  a for a in w.approvals
                  if (status is None or a.status == status) and (case_id is None or a.case_id == case_id)])),
              decide_pending=decide_pending,
              find_pending_due_for_reminder=due_for_reminder,
              mark_reminded=mark_approval_reminded)

        # ---- purchase orders & delivery
        def insert_po(po_id, case_id, vendor_id, total, lead_time, terms, expected, items, tax=None):
            w._po_seq += 1
            w.pos[case_id] = row(purchase_order_id=po_id, po_number=w._po_seq, case_id=case_id,
                                 vendor_id=vendor_id, vendor_name=w.vendors[vendor_id].name,
                                 vendor_email=w.vendors[vendor_id].email, total_amount=total,
                                 lead_time_days=lead_time, terms=terms, expected_delivery_date=expected,
                                 items_json=json.dumps(items), status="issued", created_at=now(),
                                 sent_at=None, delivery_status="pending", delivered_at=None,
                                 received_by=None, delivery_note=None, chase_count=0,
                                 last_chased_at=None, escalated_at=None, acknowledged_at=None, acknowledged_by=None,
                                 confirm_chase_count=0, last_confirm_chase_at=None, confirm_escalated_at=None, vendor_issue=None,
                                 received_json=None, short_closed_at=None, cancel_requested_at=None, cancel_requested_by=None,
                                 cancel_reason=None, cancel_chase_count=0, last_cancel_chase_at=None, cancel_escalated_at=None,
                                 cancel_refused_at=None,
                                 tax_rate_pct=tax["rate_pct"] if tax else None, tax_amount=tax["tax_amount"] if tax else None,
                                 total_with_tax=tax["total_with_tax"] if tax else None)
            return w._po_seq

        def po_by_id(po_id):
            return next(p for p in w.pos.values() if p.purchase_order_id == po_id)

        def update_po_status(po_id, status):
            po_by_id(po_id).status = status
            if status == "sent":
                po_by_id(po_id).sent_at = now()     # (the real update stamps the time it was emailed)

        def mark_chased(po_id):
            p = po_by_id(po_id)
            p.chase_count += 1
            p.last_chased_at = now()

        def mark_delivered(po_id, received_by, note):
            p = po_by_id(po_id)
            if p.delivery_status != "pending":
                return False
            p.delivery_status, p.delivered_at, p.received_by, p.delivery_note = "delivered", now(), received_by, note
            return True

        def open_deliveries():
            return [p for p in w.pos.values()
                    if p.status == "sent" and p.delivery_status == "pending"
                    and p.expected_delivery_date is not None and w.cases[p.case_id].status == "open" and p.cancel_requested_at is None]

        def mark_acknowledged(po_id, by):
            p = po_by_id(po_id)
            if p.acknowledged_at is not None:
                return False
            p.acknowledged_at, p.acknowledged_by, p.vendor_issue = now(), by, None
            return True

        def append_receipt(po_id, old_json, new_json):
            p = po_by_id(po_id)
            if p.delivery_status != "pending" or p.received_json != old_json:
                return False
            p.received_json = new_json
            return True

        def mark_short_closed(po_id, by, note):
            p = po_by_id(po_id)
            if p.delivery_status != "pending":
                return False
            p.delivery_status, p.delivered_at, p.received_by, p.delivery_note, p.short_closed_at = "delivered", now(), by, note, now()
            return True

        def mark_cancel_requested(po_id, by, reason):
            p = po_by_id(po_id)
            if p.cancel_requested_at is not None or p.delivery_status != "pending":
                return False
            p.cancel_requested_at, p.cancel_requested_by, p.cancel_reason = now(), by, reason
            p.cancel_chase_count, p.last_cancel_chase_at, p.cancel_escalated_at, p.cancel_refused_at = 0, None, None, None
            return True

        def clear_cancel_request(po_id):
            p = po_by_id(po_id)
            p.cancel_requested_at = p.cancel_requested_by = p.cancel_reason = p.last_cancel_chase_at = p.cancel_escalated_at = p.cancel_refused_at = None
            p.cancel_chase_count = 0

        def mark_cancel_chased(po_id):
            p = po_by_id(po_id)
            p.cancel_chase_count += 1
            p.last_cancel_chase_at = now()

        def update_items_and_total(po_id, items, total):
            p = po_by_id(po_id)
            p.items_json = json.dumps(items)
            if total is not None:
                p.total_amount = total

        def mark_confirm_chased(po_id):
            p = po_by_id(po_id)
            p.confirm_chase_count += 1
            p.last_confirm_chase_at = now()

        def find_unconfirmed():
            return [p for p in w.pos.values()
                    if p.status == "sent" and (p.acknowledged_at is None or p.vendor_issue) and p.delivery_status == "pending"
                    and w.cases[p.case_id].status == "open" and p.cancel_requested_at is None]

        def case_of_po_number(po_number, vendor_email):
            return next((p.case_id for p in w.pos.values()
                         if p.po_number == po_number and w.vendors[p.vendor_id].email.lower() == (vendor_email or "").lower()), None)

        patch(purchase_order_repository,
              find_all=lambda: sorted(w.pos.values(), key=lambda p: p.created_at, reverse=True),
              find_case_id_by_po_number_and_vendor_email=case_of_po_number,
              mark_cancel_requested=mark_cancel_requested,
              clear_cancel_request=clear_cancel_request,
              mark_cancel_chased=mark_cancel_chased,
              mark_cancel_escalated=lambda po_id: setattr(po_by_id(po_id), "cancel_escalated_at", now()),
              mark_cancel_refused=lambda po_id: setattr(po_by_id(po_id), "cancel_refused_at", now()),
              update_items_and_total=update_items_and_total,
              find_cancelling=lambda: [p for p in w.pos.values() if p.status == "sent" and p.cancel_requested_at is not None and w.cases[p.case_id].status == "open"],
              append_receipt=append_receipt,
              mark_short_closed=mark_short_closed,
              find_unconfirmed=find_unconfirmed,
              mark_acknowledged=mark_acknowledged,
              mark_confirm_chased=mark_confirm_chased,
              mark_confirm_escalated=lambda po_id: setattr(po_by_id(po_id), "confirm_escalated_at", now()),
              set_vendor_issue=lambda po_id, issue: setattr(po_by_id(po_id), "vendor_issue", issue),
              insert_purchase_order=insert_po,
              find_purchase_order_by_case_id=lambda cid: w.pos.get(cid),
              update_status=update_po_status,
              mark_chased=mark_chased,
              mark_escalated=lambda po_id: setattr(po_by_id(po_id), "escalated_at", now()),
              mark_delivered=mark_delivered,
              find_open_deliveries=open_deliveries)

        # ---- goods problems
        def po_for(po_id):
            return po_by_id(po_id)

        def insert_issue(issue_id, case_id, po_id, kind, items, description, reported_by):
            p = po_for(po_id)
            w.issues.append(row(issue_id=issue_id, case_id=case_id, purchase_order_id=po_id, kind=kind, items_json=json.dumps(items),
                                description=description, reported_by=reported_by, reported_at=now(), status="open", supplier_told_at=None,
                                supplier_replied_at=None, chase_count=0, last_chased_at=None, escalated_at=None, resolution=None,
                                credit_amount=None, resolution_note=None, resolved_by=None, resolved_at=None,
                                return_status=None, return_ref=None, returned_at=None, returned_by=None, replacement_status=None,
                                replacement_expected_at=None, replacement_received_at=None, credit_note_number=None,
                                po_number=p.po_number, vendor_name=p.vendor_name, vendor_email=p.vendor_email))

        def issue_by_id(issue_id):
            return next((i for i in w.issues if i.issue_id == issue_id), None)

        def resolve_issue(issue_id, resolution, credit, note, by, credit_note_number=None):
            i = issue_by_id(issue_id)
            if i is None or i.status != "open":
                return False
            i.status, i.resolution, i.credit_amount, i.resolution_note, i.resolved_by, i.resolved_at = "resolved", resolution, credit, note, by, now()
            i.credit_note_number = credit_note_number
            return True

        def mark_returned(issue_id, by, ref):
            i = issue_by_id(issue_id)
            if i is None or i.status != "open" or i.return_status:
                return False
            i.return_status, i.return_ref, i.returned_at, i.returned_by = "returned", ref, now(), by
            return True

        def mark_expected(issue_id):
            i = issue_by_id(issue_id)
            if i is None or i.status != "open" or i.replacement_status:
                return False
            i.replacement_status, i.replacement_expected_at = "expected", now()
            i.supplier_replied_at = i.supplier_replied_at or now()
            return True

        def mark_received(issue_id):
            i = issue_by_id(issue_id)
            if i is None or i.status != "open" or i.replacement_status != "expected":
                return False
            i.replacement_status, i.replacement_received_at = "received", now()
            return True

        def issue_reply(case_id):
            for i in w.issues:
                if i.case_id == case_id and i.status == "open" and i.supplier_replied_at is None:
                    i.supplier_replied_at = now()

        def issue_chased(issue_id):
            i = issue_by_id(issue_id)
            i.chase_count += 1
            i.last_chased_at = now()

        patch(goods_issue_repository,
              insert_issue=insert_issue,
              find_by_case=lambda cid: [i for i in w.issues if i.case_id == cid],
              find_by_id=issue_by_id,
              find_open=lambda: [i for i in w.issues if i.status == "open" and w.cases[i.case_id].status == "open"],
              mark_supplier_told=lambda iid: setattr(issue_by_id(iid), "supplier_told_at", now()),
              mark_supplier_replied=issue_reply,
              mark_chased=issue_chased,
              mark_escalated=lambda iid: setattr(issue_by_id(iid), "escalated_at", now()),
              mark_returned=mark_returned, mark_replacement_expected=mark_expected, mark_replacement_received=mark_received,
              resolve=resolve_issue)

        # ---- invoices
        def insert_invoice(invoice_id, case_id, po_id, vendor_id, number, total, raw, extracted, status,
                           issues, source, tax=None):
            tax = tax or {}
            po = po_by_id(po_id)
            w.invoices.append(row(invoice_id=invoice_id, case_id=case_id, purchase_order_id=po_id,
                                  vendor_id=vendor_id, vendor_name=w.vendors[vendor_id].name,
                                  po_number=po.po_number, invoice_number=number, total_amount=total,
                                  status=status, issues=json.dumps(issues), source=source,
                                  subtotal=tax.get("subtotal"), tax_rate_pct=tax.get("tax_rate_pct"), tax_amount=tax.get("tax_amount"),
                                  decided_by=None, decision_note=None, created_at=now(), decided_at=None))

        def decide_open(invoice_id, status, by, note):
            for i in w.invoices:
                if i.invoice_id == invoice_id and i.status in ("mismatch", "on_hold"):
                    i.status, i.decided_by, i.decision_note, i.decided_at = status, by, note, now()
                    return True
            return False

        def update_evaluation(invoice_id, status, issues):
            for i in w.invoices:
                if i.invoice_id == invoice_id:
                    i.status, i.issues = status, json.dumps(issues)

        patch(invoice_repository,
              insert_invoice=insert_invoice,
              number_exists=lambda vid, num: any(i.vendor_id == vid and i.invoice_number == num
                                                 and i.status != "rejected" for i in w.invoices),
              find_by_id=lambda iid: next((i for i in w.invoices if i.invoice_id == iid), None),
              find_by_case_id=lambda cid: [i for i in w.invoices if i.case_id == cid],
              find_all=lambda status=None: [i for i in w.invoices if status is None or i.status == status],
              update_evaluation=update_evaluation,
              decide_open=decide_open)

        # ---- people, email, mailbox, AI
        patch(user_repository,
              find_all_users=lambda: [],
              find_active_users_with_permission=lambda permission: [row(email=e, user_id=f"00000000-0000-0000-0000-{i:012d}", username=e) for i, e in enumerate(w.managers)])
        patch(email_client, send_email=lambda to, subject, body, html=None: w.sent.append((to, subject, body)))

        # ---- one-tap approval links
        def insert_link(link_id, approval_id, user_id, token_hash, expires_at):
            w.links.append(row(link_id=link_id, approval_id=approval_id, user_id=user_id, token_hash=token_hash, created_at=now(),
                               expires_at=expires_at, used_at=None, used_action=None, revoked_at=None))

        def revoke_links(approval_id, user_id=None):
            for l in w.links:
                if l.approval_id == approval_id and (user_id is None or l.user_id == user_id) and l.used_at is None and l.revoked_at is None:
                    l.revoked_at = now()

        def use_link(link_id, action, ip):
            for l in w.links:
                if l.link_id == link_id and l.used_at is None and l.revoked_at is None and l.expires_at >= now():
                    l.used_at, l.used_action = now(), action
                    return True
            return False

        # ---- documents no order could be found for
        def insert_document(from_email, vendor_name, subject, summary, file_names, payload):
            document_id = str(uuid.uuid4())
            w.documents.append(row(document_id=document_id, from_email=from_email, vendor_name=vendor_name, subject=subject, summary=summary,
                                   file_names=file_names, payload=payload, status="open", case_id=None, handled_by=None, handled_at=None,
                                   note=None, created_at=now()))
            return document_id

        def mark_document_handled(document_id, status, handled_by, case_id, note):
            for d in w.documents:
                if d.document_id == document_id and d.status == "open":
                    d.status, d.handled_by, d.case_id, d.note, d.handled_at = status, handled_by, case_id, note, now()
                    return True
            return False

        patch(read_file_repository,
              known_hashes=lambda case_id: set(w.read_files.get(case_id, set())),
              find_all=lambda limit=5000: [row(case_id=cid, file_hash=h, file_name=w.read_file_names.get((cid, h), "(file)"), first_read_at=now()) for cid, hs in w.read_files.items() for h in hs if w.read_file_names.get((cid, h)) != "(email text)"],
              remember=lambda case_id, files: (w.read_files.setdefault(case_id, set()).update(h for h, _ in files), w.read_file_names.update({(case_id, h): n for h, n in files}))[0])

        patch(unmatched_document_repository,
              insert_document=insert_document,
              find_open=lambda: [d for d in reversed(w.documents) if d.status == "open"],
              find_by_id=lambda i: next((d for d in w.documents if d.document_id == i), None),
              mark_handled=mark_document_handled)

        def revoke_user_links(user_id):
            n = 0
            for l in w.links:
                if l.user_id == user_id and l.used_at is None and l.revoked_at is None:
                    l.revoked_at = now()
                    n += 1
            return n

        patch(approval_link_repository, insert_link=insert_link, revoke_for=revoke_links, revoke_for_user=revoke_user_links, mark_used=use_link,
              find_by_hash=lambda h: next((l for l in w.links if l.token_hash == h), None))

        def process_inbox(handler):
            batch, w.inbox = w.inbox, []
            for message in batch:
                handler(message)
            return len(batch)

        monkeypatch.setattr(worker.imap_client, "process_unseen_replies", process_inbox)
        monkeypatch.setattr(azure_openai_client, "ask_json", w._fake_ai)
        return self

    # ---------- the AI, replaced by simple deterministic rules ----------
    def _fake_ai(self, system_prompt, user_prompt, temperature=0.1, images=None):
        if images:                                            # a fake page picture can carry its own text (see clients/ai_stub.py)
            from app.clients import ai_stub
            user_prompt = ai_stub._with_picture_text(user_prompt, images)
        if "Procurement Agent" in system_prompt:
            wanted = re.search(r"Requested item: (.+)", user_prompt).group(1).strip()
            return {"stock_item": self.stock_ai.get(wanted)}
        if "Purchase Agent" in system_prompt:
            return self.parsed_requests[user_prompt]
        if "raw vendor quote" in system_prompt:
            price = re.search(r"Rs ([\d,]+)", user_prompt)
            days = re.search(r"(?<!valid )(?<!for )(\d+) days", user_prompt, re.I)
            terms = re.search(r"Terms: (.+)", user_prompt)
            valid = re.search(r"valid (?:for )?(\d+) days", user_prompt, re.I)
            return {"price": float(price.group(1).replace(",", "")) if price else None,
                    "valid_days": int(valid.group(1)) if valid else None,
                    "lead_time_days": int(days.group(1)) if days else None,
                    "terms": terms.group(1).strip() if terms else None}
        if "Rank ALL the vendors" in system_prompt:
            quotes = ast.literal_eval(user_prompt[len("Quotes: "):])
            by_price = sorted((q for q in quotes if q["price"] is not None), key=lambda q: q["price"])
            return {"ranking": [{"vendor_id": q["vendor_id"], "reason": f"{q['vendor_name']} is #{i + 1} on price."} for i, q in enumerate(by_price)],
                    "recommended_vendor_id": by_price[0]["vendor_id"], "rationale": f"{by_price[0]['vendor_name']} is cheapest."}
        if "You are the PO Agent" in system_prompt and "to CANCEL a purchase order" in system_prompt:
            text = user_prompt.lower()
            if any(w in text for w in ("cannot be cancelled", "can't cancel", "already shipped", "already dispatched")):
                return {"kind": "refused"}
            if any(w in text for w in ("cancelled", "agree", "no problem")):
                return {"kind": "agreed"}
            return {"kind": "other"}
        if "You are the PO Agent" in system_prompt:
            text = user_prompt.lower()
            asked = re.search(r"(?:now|revised|new)[^0-9]{0,20}([\d,]{4,})", text)
            if asked:
                return {"kind": "problem", "issue": "Asks for a different price.", "new_price": float(asked.group(1).replace(",", ""))}
            if any(w in text for w in ("cannot", "can't", "unable", "sorry", "price has gone up")):
                return {"kind": "problem", "issue": "The supplier says they cannot deliver as ordered."}
            if any(w in text for w in ("confirm", "received your order", "will deliver", "order received", "accepted")):
                return {"kind": "confirmed", "issue": None}
            return {"kind": "other", "issue": None}
        if "Invoice Agent" in system_prompt:
            if not user_prompt.lstrip().lower().startswith("invoice"):
                return {"is_invoice": False, "invoice_number": None, "total_amount": None,
                        "po_number": None, "items": []}
            number = re.search(r"Invoice (\S+?)[ .,]", user_prompt)
            total = re.search(r"Total Rs ([\d,]+)", user_prompt)
            po = re.search(r"PO-\d+", user_prompt)
            qty = re.search(r"(\d+) x ([\w ]+?)[.,]", user_prompt)
            sub = re.search(r"Subtotal Rs ([\d,.]+?)[.,]? ", user_prompt + " ")
            rate = re.search(r"(?:GST|Tax) (\d+(?:\.\d+)?)%", user_prompt)
            tax_amount = re.search(r"Tax amount Rs ([\d,.]+?)[.,]? ", user_prompt + " ")
            return {"is_invoice": True,
                    "subtotal": float(sub.group(1).replace(",", "")) if sub else None,
                    "tax_rate_pct": float(rate.group(1)) if rate else None,
                    "tax_amount": float(tax_amount.group(1).replace(",", "")) if tax_amount else None,
                    "invoice_number": number.group(1) if number else None,
                    "total_amount": float(total.group(1).replace(",", "")) if total else None,
                    "po_number": po.group(0) if po else None,
                    "items": [{"description": qty.group(2), "quantity": int(qty.group(1))}] if qty else []}
        raise AssertionError(f"Unexpected AI prompt: {system_prompt[:60]}")


def standard_world(monkeypatch) -> World:
    """Three suppliers (two trusted, one not), some stock, a manager to notify, and a taught request."""
    w = World().install(monkeypatch)
    w.add_vendor("Acme", 4.5)
    w.add_vendor("Globex", 4.2)
    w.add_vendor("Initech", 3.0)
    w.add_stock("Laptop", 100)
    w.add_stock("CCTV camera", 20)
    w.teach("10 laptops", [{"description": "Laptop", "quantity": 10}])
    w.teach("50 cameras", [{"description": "CCTV camera", "quantity": 50}])
    return w


_ = date  # (date is used by tests via this module's namespace)
