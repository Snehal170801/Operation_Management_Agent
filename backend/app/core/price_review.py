"""What an approver sees for a supplier's request for a higher price: what was agreed, what they ask now, and their own words."""


def build_price_review(approval: dict, case: dict, po: dict | None, proposal: dict | None) -> dict:
    return {
        "approval_id": approval["approval_id"], "case_id": approval["case_id"], "case_number": case.get("case_number"),
        "status": approval["status"], "reasons": approval["reasons"], "requested_by": case.get("requester_id"),
        "request_text": None, "items": [{"description": i["description"], "quantity": i["quantity"]} for i in (po or {}).get("items", [])],
        "kind": "price_change",
        "price_change": None if not proposal else {
            "po_number": proposal.get("po_number"), "vendor_name": proposal.get("vendor"), "agreed_total": proposal.get("old_total"),
            "new_total": proposal.get("new_total"), "pct": proposal.get("pct"), "reply_text": proposal.get("snippet") or "",
        },
    }
