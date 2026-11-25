"""The document store: one searchable list of every document the system holds about a case: purchase orders, invoices, quotes and the files
suppliers sent. Built from what is already stored (nothing extra is kept), so it is always in step with the cases.

Pure functions over plain dicts: no database, clock or AI. A requester gets a SANITISED view of their own cases only (no supplier, no amount, no
quote, no file name): the same rule as their timeline.
"""

KINDS = ("purchase_order", "invoice", "quote", "file")
LABEL = {"purchase_order": "Purchase order", "invoice": "Invoice", "quote": "Quote", "file": "File from a supplier"}
REQUESTER_KINDS = ("purchase_order", "invoice")          # the only documents a requester sees listed, and only as "there is one"
MAX_LIMIT = 100


def _item(kind: str, doc_id: str, title: str, case: dict, case_id: str, vendor, amount, status, at) -> dict:
    return {"id": f"{kind}:{doc_id}", "kind": kind, "kind_label": LABEL[kind], "title": title, "case_id": case_id, "case_number": case.get("case_number"),
            "vendor": vendor, "amount": amount, "status": status, "at": at}


def build(cases: dict[str, dict], pos: list[dict], invoices: list[dict], quotes: list[dict], files: list[dict]) -> list[dict]:
    """Every document, newest first. `cases` is {case_id (lower case): case}; rows whose case is unknown still appear (without a number)."""
    items: list[dict] = []
    for p in pos:
        case = cases.get(p["case_id"].lower(), {})
        items.append(_item("purchase_order", p["purchase_order_id"], p["po_number"], case, p["case_id"], p.get("vendor_name"),
                           p.get("total_with_tax") if p.get("total_with_tax") is not None else p.get("total_amount"), (p.get("status") or "").replace("_", " "), p.get("created_at")))
    for i in invoices:
        case = cases.get(i["case_id"].lower(), {})
        items.append(_item("invoice", i["invoice_id"], f"Invoice {i['invoice_number']}" if i.get("invoice_number") else "Invoice (number unreadable)", case, i["case_id"],
                           i.get("vendor_name"), i.get("total_amount"), (i.get("status") or "").replace("_", " "), i.get("created_at")))
    for q in quotes:
        case = cases.get(q["case_id"].lower(), {})
        items.append(_item("quote", q["quote_id"], f"Quote from {q['vendor_name']}", case, q["case_id"], q.get("vendor_name"), q.get("price"), None, q.get("created_at")))
    for f in files:
        case = cases.get(f["case_id"].lower(), {})
        items.append(_item("file", f"{f['case_id']}:{f['file_hash'][:12]}", f.get("file_name") or "(unnamed file)", case, f["case_id"], None, None, None, f.get("first_read_at")))
    return sorted(items, key=lambda i: (i["at"] is not None, i["at"]), reverse=True)


def _haystack(item: dict) -> str:
    amount = item.get("amount")
    money = f"{amount:,.2f} {amount:.2f} {amount:.0f}" if isinstance(amount, (int, float)) else ""
    return " ".join(str(x) for x in (item["title"], item["kind_label"], item["kind"], item.get("case_number") or "", item.get("vendor") or "", item.get("status") or "", money)).lower()


def search(items: list[dict], query: str | None, kind: str | None, limit: int = 25, offset: int = 0) -> dict:
    """One page of matches plus the totals. Every word of `query` must appear somewhere (title, case number, supplier, status, amount). `counts` is
    how many match per kind ignoring the kind filter, so the screen can show the tabs. Limits are clamped; an unknown kind matches nothing."""
    words = [w for w in (query or "").lower().split() if w]
    matching = [i for i in items if all(w in _haystack(i) for w in words)]
    counts = {k: sum(1 for i in matching if i["kind"] == k) for k in KINDS}
    chosen = matching if not kind else [i for i in matching if i["kind"] == kind]
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    return {"items": chosen[offset:offset + limit], "total": len(chosen), "counts": counts, "limit": limit, "offset": offset}


def for_requester(items: list[dict], owned_case_ids: set[str]) -> list[dict]:
    """What a requester may see: only documents of their own cases, only orders and invoices, and only that one exists (a generic title, the
    case number and the date). No supplier, no amount, no status, no quote, no file name."""
    owned = {c.lower() for c in owned_case_ids}
    out = []
    for i in items:
        if i["kind"] in REQUESTER_KINDS and i["case_id"].lower() in owned:
            out.append({**i, "title": f"{LABEL[i['kind']]} for {i['case_number'] or 'your request'}", "vendor": None, "amount": None, "status": None})
    return out
