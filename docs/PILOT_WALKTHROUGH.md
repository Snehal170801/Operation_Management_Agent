# Pilot walkthrough

A hands-on test of the whole automatic flow, using a separate pilot database and your own inbox.
You play the suppliers; the agents do everything else.

## 1. Set up (about 20 minutes)

1. **Create an empty SQL Server database** for the pilot (for example `operation_agents_pilot`) and point
   `SQL_DATABASE` in `backend/.env` at it. Never run a pilot against real data.
2. **Fill in `backend/.env`** (see `.env.example` for every setting). For the pilot you need:
   - `JWT_SECRET`, `AZURE_OPENAI_*`
   - `SMTP_*` and `IMAP_*` for **one dedicated mailbox** (e.g. `pilot@yourco.com`). Use the same address
     for `SMTP_FROM`, so supplier replies come back to the mailbox the system reads.
   - For quicker testing set `RFQ_DEADLINE_HOURS=1`, `RFQ_REMINDER_HOURS=1`, `DELIVERY_CHASE_INTERVAL_HOURS=1`.
3. From the `backend` folder:
   ```
   python -m scripts.migrate
   python -m scripts.seed_pilot --admin you@yourco.com --manager boss@yourco.com --user ravi@yourco.com --vendor-mailbox pilot@yourco.com
   python -m scripts.preflight --live-ai
   ```
   Fix every **FAIL** the preflight shows. A **WARN** is allowed but tells you what will not be automatic.
4. Start the API (`uvicorn app.main:app --port 8000`) and the frontend (`npm run dev` in `frontend`).

The seed script creates three suppliers whose addresses are `pilot+acme@…`, `pilot+globex@…`,
`pilot+initech@…`. They all arrive in **your** pilot mailbox, so you can reply as each supplier.
Stock: 100 laptops, 20 CCTV cameras, 0 NVRs.

## 2. The two sides

| Sign in as | You see |
|---|---|
| **Requester** (`ravi@…`, role *User*) | "My requests" only: a box to type a request, your own requests, and a live step tracker. No prices, suppliers or other people's requests. |
| **Manager / Admin** | Everything: Dashboard (with **Needs attention**), Cases, Approvals, Stock, Vendors, Settings. |

Keep two browser windows open (one normal, one private) to watch both sides at once.

## 3. Scenarios

Run them in order. For each: what to do, and what you should see.

### A. Enough stock - fully automatic
*As the requester:* submit **"I need 10 laptops for the sales team"**.
**Expect:** within seconds the tracker shows "available in stock" and the case is closed. Laptops go from 100 to 90 on the Stock page. No emails.

### B. Routine purchase - no human at all
*As the requester:* submit **"I need 50 CCTV cameras for the Pune site"**.
**Expect:**
1. Tracker: "asking suppliers for prices". Three emails arrive in the pilot mailbox, one per supplier, subject starting `[OA-…] Request for quotation`.
2. *You, as the suppliers.* **Reply** (do not write a new email; the subject tag must stay) from the pilot mailbox. The system reads the *plain text* of the reply, so write it like this:
   - As Acme: `Total Rs 42,000. Delivery 7 days. Terms: 50% advance`
   - As Globex: `Total Rs 45,000. Delivery 5 days. Terms: net 30`
   **Important:** an emailed reply is matched to a supplier by its **sender address**, and with one test mailbox your replies come from `pilot@…`, not `pilot+acme@…`. So for the pilot, simplest is to enter each quote by hand: open the case (as staff) → **Suppliers & quotes → Add a quote by hand**, choose the supplier and paste the same text. It goes through exactly the same reading and ranking. (With real suppliers, who each write from their own address, emailed replies match automatically.)
3. Wait for the quote deadline (or all suppliers to reply). The worker ranks the quotes and, because the amount is under ₹50,000, the supplier is trusted and there are two quotes, **approves automatically**.
4. A purchase order email (`[OA-…] Purchase Order PO-1001`) goes to the winning supplier. The case page shows the PO.
**Expect no email to the manager.**
5. As staff open the case → **Delivery → Mark as received**. Then reply to the PO email as the supplier: `Invoice INV-7 for PO-1001. Total Rs 42,000. 50 x CCTV camera.`
**Expect:** the invoice shows **Matched** and the case closes by itself.

### C. Something unusual - a person decides
Repeat B but reply with quotes above ₹50,000 (e.g. `Total Rs 90,000`), or reply from only one supplier, or make Initech the cheapest.
**Expect:** the case stops at "Waiting for approval". The manager gets an email with the reasons. Open **Approvals** and approve or reject.
- **Approve** → the order is placed at once.
- **Reject** → the case closes as rejected; the requester sees "wasn't approved".

### D. Nobody replies
Submit another request and do not reply. After the deadline the manager is emailed "No vendor quotes were received", and the case appears under **Needs attention** on the dashboard.

### E. Late delivery
Place an order (B), then in the database set the PO's `expected_delivery_date` to a past date. **Expect:** the supplier gets "Delivery follow-up" emails, then the manager is told once the follow-ups run out.

### F. A wrong invoice
After receiving the goods, reply as the supplier with `Invoice INV-8 for PO-1001. Total Rs 49,000. 50 x CCTV camera.`
**Expect:** the invoice shows **Mismatch** with the reason, the manager is emailed, the case stays open. Staff can **Approve anyway** or **Reject**. Send the *same* invoice twice to see the duplicate flag.

### G. The pause switch
*As admin:* Settings → Automation → **Pause**. Submit a request. **Expect:** it is accepted but no supplier emails go out and the dashboard shows a banner. **Resume**: within a few minutes the held request is picked up.

### H. Privacy check
Sign in as the requester and try to open another person's case URL, or `/stock`, `/vendors`, `/approvals`. **Expect:** "not found" or "no access", never the data.

## 4. If something does not happen

| Symptom | Check |
|---|---|
| No supplier emails | `scripts.preflight`; supplier has an email (Vendors page); automation not paused |
| Replies are not picked up | Replied to the original email (subject keeps `[OA-…]`); IMAP works in preflight; the sender address matches a supplier |
| Case stuck at "Waiting for approval" | Open Approvals; this is waiting for a person by design |
| Nothing advances at all | `WORKER_ENABLED=true`; only one API instance running; automation not paused |
| An email says it was only logged | `SMTP_HOST` is empty: emails are written to the API log |

Every step is recorded on the case's **Timeline** (staff view), and every approval, rejection and pause is in the **Audit log**.

## 5. Before real use

- Replace the pilot limits in `.env` with your real ones (`AUTO_APPROVE_*`).
- Run on HTTPS with `COOKIE_SECURE=true` and a real `APP_BASE_URL`.
- Keep **one** API instance running the worker, or rely on the built-in lease if you run several.
- Known gaps: the supplier's confirmation of a PO is only logged; scanned (image-only) PDFs and photos cannot be read, so a person is pointed to the email to enter the details by hand.

## 6. Extra things to try

**Stock wording.** The stock check understands different wording, plurals and common short forms. Submit these as the requester and watch what happens (stock items are in `scripts/stock_catalog.py`):

| Type this | Expect |
|---|---|
| `I need 5 laptops` | In stock (matches "Laptop") |
| `3 tabs` | In stock (matches "Tablet") |
| `2 phones` | In stock (matches "Mobile phone") |
| `4 ceiling fans` | In stock |
| `a 24 inch monitor` | In stock (matches "Monitor 24 inch") |
| `4 screens` or `a fan` or `an AC` | Goes to suppliers, because the size or type is not clear. This is deliberate: the system never guesses between similar items |
| `2 Dell laptops` | Goes to suppliers (a specific brand we don't stock separately) |

**Files as quotes and invoices.** Reply as the supplier with the quote or invoice as a **PDF, Excel (.xlsx) or CSV attachment** instead of typing it in the email. It is read the same way. A scanned PDF (a photo of paper) cannot be read: the case timeline will say which file, and a person enters it by hand.
