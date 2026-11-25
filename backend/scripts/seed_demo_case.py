"""Create one COMPLETE demo case that every agent works on, for showing off the Agent Flow replay.

    python -m scripts.seed_demo_case [--requester you@example.com]

It drives the real pipeline end to end (real database, real AI), so the case has genuine recorded steps:
  Purchase reads the request -> Procurement finds stock too low -> Vendor asks 3 suppliers, reads their
  quotes and compares them -> Approval needs a person (the order is large) and a manager approves ->
  PO sends the order -> Delivery sees the goods arrive -> Invoice reads and matches the invoice -> done.

No email is sent (sending is switched off for this script only), so it is safe to run any time.
It does create a real case in the database; run it once and keep it, or delete the case afterwards.
"""

import argparse
import sys

from app.agents import approval_agent, operations_agent, purchase_order_agent, vendor_agent
from app.clients import email_client
from app.orchestrator import case_pipeline

REQUEST = "We need 50 CCTV cameras for the new warehouse in Pune"

# Large enough that the approval policy asks a person (over the auto-approve limit).
QUOTES = {
    "Acme Supplies": "Total Rs 92,000. Delivery 7 days. Terms: 50% advance, balance on delivery",
    "Globex Traders": "Total Rs 96,500. Delivery 5 days. Terms: net 30, 2 year warranty",
    "Initech Imports": "Total Rs 88,000. Delivery 10 days. Terms: net 15",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requester", default="demo.requester@example.com", help="who the request is filed for")
    parser.add_argument("--approver", default="demo.manager@example.com", help="the name recorded as approving it")
    args = parser.parse_args()

    # Nothing in this run may email a real supplier or manager.
    email_client.send_email = lambda to, subject, body: print(f"   (email not sent: {subject})")

    print("1. Submitting the request ...")
    case_id = case_pipeline.start_case(args.requester, REQUEST)
    case = operations_agent.get_case_status(case_id)
    print(f"   {case['case_number']}  stage: {case['stage']}")
    if case["stage"] != "awaiting_quotes":
        print("   The stock covered this request, so no suppliers were needed. Reduce the stock of 'CCTV camera' and retry.")
        return 1

    print("2. Suppliers reply with their quotes ...")
    vendors = {v["name"]: v["vendor_id"] for v in vendor_agent.get_all_vendors()}
    for name, text in QUOTES.items():
        with operations_agent.working(case_id, "read_quote"):
            quote = vendor_agent.submit_quote(case_id, vendors[name], text)
        print(f"   {name}: {quote['price']:,.0f}, {quote['lead_time_days']} days")

    print("3. The Vendor agent compares the quotes and the Approval agent checks the rules ...")
    action = case_pipeline.advance_sourcing(case_id)
    print(f"   worker decision: {action}")

    pending = approval_agent.get_approvals(status="pending", case_id=case_id)
    if pending:
        print(f"4. A person is needed: {pending[0]['reasons'][0]}")
        case_pipeline.decide_approval(pending[0]["approval_id"], True, args.approver, "Approved: needed urgently for the warehouse")
        print(f"   approved by {args.approver}")
    else:
        print("4. The order was approved automatically.")

    po = purchase_order_agent.get_purchase_order(case_id)
    print(f"5. Order {po['po_number']} sent to {po['vendor_name']} for {po['total_amount']:,.2f}")

    print("6. The goods arrive ...")
    case_pipeline.confirm_delivery(case_id, args.approver, "All 50 cameras received and checked")

    print("7. The supplier's invoice arrives ...")
    invoice = case_pipeline.process_invoice(
        case_id,
        f"Invoice INV-DEMO-0001 for {po['po_number']}. Supplier: {po['vendor_name']}. "
        f"50 x CCTV Camera. Total Rs {po['total_amount']:,.2f} including GST.",
        source="manual",
    )
    print(f"   invoice {invoice['invoice_number']}: {invoice['status']}")

    final = operations_agent.get_case_status(case_id)
    print(f"\nDone: {final['case_number']} is now '{final['stage']}' ({final['status']}).")
    print("Open Agent Flow, pick it in the list, and press Play on the replay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
