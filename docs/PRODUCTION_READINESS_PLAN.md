# Operation Agents: component-by-component production-readiness plan

Written 6 October 2026. Companion to `PROJECT_STATUS_AND_PRODUCTION_CHECKLIST.txt` (what is left overall).

## 1. The idea

We have built the whole system. Now we go **one component at a time**, in depth, until each one is *production ready*, and then the product is.
For every component we do the same five steps:

1. **List** what it does, what comes in, what goes out, and every state it can be in.
2. **Audit**: for each case (happy path, wrong input, silence, failure, too slow), write down what the system does today, who is told, and what happens if nobody answers.
3. **Fix** every gap found.
4. **Test**: a unit test for the rule, a failure-case test, and where it has a screen, a browser test.
5. **Sign off**: tick the checklist in section 2 and record it in section 3.

## 2. What "production ready" means for one component

A component is done only when **all** of these are true:

- [ ] **Every case is defined.** Happy path, bad input, supplier silence, a failing service, a too-slow answer: each has a defined outcome.
- [ ] **Nothing is silent.** Every outcome is visible on the case timeline, and if a person is needed they are told (right department by email and in My work; the admin if nobody acts).
- [ ] **Nothing is stuck.** Anything waiting has a timer: it reminds, then escalates. A general "stuck too long" check exists for this stage.
- [ ] **It is real-time.** The screen updates by itself; no refresh, no hidden delay.
- [ ] **It is safe.** Permissions are enforced on the server; requesters see only their own cases; every action is in the audit log; inputs are size-limited and validated; text from outside (supplier emails and PDFs) is never trusted.
- [ ] **It is configurable.** Limits and timings are settings (Settings > Configure), with safe defaults.
- [ ] **It is tested.** Unit tests, failure-case tests, and a browser test where there is a screen. All green twice in a row.
- [ ] **It is observable.** Health is on the system health page; failures are logged with a request id.
- [ ] **It recovers.** A restart, a crash, or a retry never loses or duplicates work (safe to run twice).
- [ ] **It is documented.** One paragraph in the admin guide: what it does, what can go wrong, what to do.

## 3. The component list (work order)

Order is by risk: things that can lose money or lose track of work first.
Status: `[ ]` not audited, `[~]` audited / partly fixed, `[x]` production ready.
"Known gaps" are what we already know; the audit will find more.

### A. Coordination and intake (the backbone)

| # | Component | Known gaps to start with | Status |
|---|---|---|---|
| A1 | **Mailbox intake** (`imap_client`, `worker`) | Worker and mailbox watcher stalled ~25 min with nobody told, cause unknown. No watchdog. Mail from unknown senders is never fetched. Auto-replies (out of office) and mail loops not handled. HTML-only mail, inline images, forwarded mail untested. | [ ] |
| A2 | **Document reading** (`attachments`, AI vision) | Scans and photos now read (new). Unknown types (zip, docx) unreadable. Prompt-injection risk from supplier text going into AI prompts. No file-hash memory (same PDF read twice). | [~] |
| A3 | **Coordinator** (`case_pipeline`, stage machine) | No general "stuck too long" sweep for every stage. Idempotency on restart and retry not audited stage by stage. Pause switch and worker lease need a failure test. | [ ] |
| A4 | **Background worker** (`worker`, health, escalation) | Silent stall (above). Alert when a loop dies. Auto-restart. | [ ] |
| A5 | **Notification** (`notification_agent`) | A department with no email falls back to admins; what if the admin has none? Email send failures only logged. Unmatched documents only emailed to Accounts. Alert fatigue (many emails for one problem). | [ ] |
| A6 | **Live updates** (`live`, SSE, polling) | "Reading..." status for documents not built. Behaviour when the live stream drops. | [ ] |

### B. The seven agents

| # | Agent / area | Known gaps to start with | Status |
|---|---|---|---|
| B1 | **Purchase** (read the request) | Unclear or multi-line requests; other languages; very large quantities; requester edits after sending; cost-centre reading. | [ ] |
| B2 | **Procurement and stock** | Stock returned if a case is cancelled? Matching only by same words. Units. Negative or reserved stock. Reorder trigger is manual only. | [ ] |
| B3 | **Vendor** (quotes) | Quote with no price; quote for only some items; supplier declines; supplier asks a question; out-of-office; one supplier only; currency or tax mentioned; quote validity. | [ ] |
| B4 | **Approval** | Approver on leave (KNOWN GAP: there is no "on leave" status in the data, so leave is not detected; a person with no e-mail address, or the requester being the only approver, IS detected and goes to the admins); no backup approver; approval email links when the approver has no email; amount changes after approval; many approvers answering at once. | [ ] |
| B5 | **Purchase order** | PO email fails; supplier says cannot supply; tax (GST) not modelled; change requests after order; PO numbering gaps; PDF file name has a doubled "PO-". | [ ] |
| B6 | **Delivery** | Over-delivery (more than ordered); wrong location; goods arriving before the order is confirmed; requester dispute flow; damaged-goods stock rule follows later issue resolution. | [ ] |
| B7 | **Invoice** | Credit notes; proforma invoices; tax lines; invoice for a different order; invoice after the case closed; over-billing beyond tolerance; payment status (Finance stage skipped). | [ ] |

### C. Screens and people

| # | Component | Known gaps to start with | Status |
|---|---|---|---|
| C1 | **My work** (department queues) | Count badge; unmatched documents not in queues; items with no owner. | [ ] |
| C2 | **Approvals screen and email** | Review card complete? Reminders and escalation chain. | [ ] |
| C3 | **Cases, Agent Flow, replay** | Unknown case shows empty panels; console 404 noise. | [ ] |
| C4 | **Unmatched documents** | New: needs a "who is handling this" owner and an age/escalation timer. | [~] |
| C5 | **Stock, Store Room, Vendors screens** | Exports not built; Store Room does not show unit and category. | [ ] |
| C6 | **Reports and Dashboard** | Numbers checked against real data; large-data speed. | [ ] |
| C7 | **Users, permissions, departments** | Password rules, forced change on first login, session handling, deactivation effect on open items. | [ ] |
| C8 | **Settings and Configure** | Validation of every limit; audit of changes; reset to defaults. | [ ] |
| C9 | **Documents (PDF)** | Printable PO and approval summary built; company details; file naming bug. | [~] |
| C10 | **Frontend shell** | Session expiry, offline message, error boundaries, mobile and accessibility checks (test phase 6). | [ ] |

### D. Platform

| # | Component | Known gaps to start with | Status |
|---|---|---|---|
| D1 | **Email client** (SMTP) | Company mailbox instead of personal Gmail; sending limits; bounce loop. | [ ] |
| D2 | **AI client** | Daily cost limit and alert; behaviour when Azure is down or slow; page-image cost. | [ ] |
| D3 | **Database and migrations** | Duplicate migration numbers 011 and 017 (old); indexes; backups and restore test; separate production database; data retention. | [ ] |
| D4 | **Security (cross-cutting)** | Default passwords; exposed tokens to rotate; production settings; rate limits on every public route; prompt injection; file limits. | [ ] |
| D5 | **Servers and operations** | Auto-start as a service; real domain and HTTPS; monitoring; deploy and rollback; admin guide. | [ ] |
| D6 | **Test suite** | Browser phases 5 to 8; nightly run; real sample PDFs; speed test. | [~] |

## 4. First case matrix: every document a supplier can send

Fill this in during audit A1/A2/B3/B5/B7. "Today" is our best current knowledge.
`OK` = handled and tested, `PART` = partly handled (usually: no person told), `GAP` = silent or wrong, `CHECK` = not verified.
Every row must end as **one visible result**, with a person told when one is needed.

### While waiting for quotes
| Case | Today | What it should do |
|---|---|---|
| Quote typed in the email | OK | Read, record, rank |
| Quote as text PDF | OK | Read, record |
| Quote as scan or photo | OK (new) | Read by AI; if unreadable, alert and ask to resend |
| Quote as Excel | OK | Read |
| Reply with no price | CHECK | Record as "no price", ask the supplier, tell Vendor team |
| Quote for only some items | CHECK | Flag as partial, tell Vendor team |
| Supplier declines ("cannot supply") | CHECK | Mark declined, count as an answer, tell Vendor team |
| Supplier asks a question | CHECK | Tell Vendor team; keep the case waiting visibly |
| Revised quote | OK | Re-rank; re-ask approval if needed |
| Reply after the choice was made | PART | Logged only. Should tell a person |
| Reply from a sender who was not invited | PART | Logged only. Should tell Vendor team |
| Out-of-office auto-reply | CHECK | Ignore, never loop |
| Same email twice | CHECK | Ignore the duplicate, note it |
| Bounce (address does not work) | OK | Flag the supplier, tell Vendor team |

### After the order
| Case | Today | What it should do |
|---|---|---|
| "Confirmed" | OK | Mark confirmed |
| "Delivered" (claim) | CHECK | Tell Receiving to verify; do not mark received |
| Our own PO PDF sent back | **GAP** | Recognise as "our own document", tell the PO desk, ask for what was needed |
| Price increase | OK | Approver decides |
| "Cannot supply as ordered" | OK | Tell PO desk |
| Reply to a cancellation | OK | Cancel or tell PO desk |
| Reply about faulty goods | OK | Record for the person handling it |

### Invoice
| Case | Today | What it should do |
|---|---|---|
| Invoice typed or text PDF | OK | Match, close if clean |
| Invoice as scan or photo | OK (new) | Read by AI, match |
| Invoice with no invoice number | PART | Asks the supplier; should also tell Accounts |
| Wrong total or items | OK | Accounts decides |
| Duplicate invoice number | OK | Flag |
| Invoice that names another order | PART | Treated as unmatched; check wording to Accounts |
| Credit note | CHECK | Recognise, reduce the payable, tell Accounts |
| Proforma invoice | CHECK | Recognise as not a bill, ask for the final one |
| Several part invoices | OK | Match each to what arrived |
| Invoice before delivery | OK | Wait quietly, release on receipt |
| Invoice after the case closed | CHECK | Flag as possible duplicate to Accounts |
| Unreadable or locked file | OK (new) | Alert, ask to resend |
| Zip or unknown file type | CHECK | Alert, ask to resend |

### Outside any order
| Case | Today | What it should do |
|---|---|---|
| Fresh email from a known supplier with a PO number | OK (new) | Find the order from the number |
| Fresh email from a known supplier, no order named | OK (new) | Keep in Unmatched documents, tell Accounts |
| Supplier newsletter | OK | Ignored by design |
| Email from a stranger | OK | Not read at all |

## 5. Working method

- **One component at a time**, in the order of section 3. Do not start the next until the current one has its checklist ticked.
- **Team:** the team lead keeps this file current and reviews every handoff; the developer fixes gaps; the tester turns each case into a browser test. Each reports one short message per component.
- **Every gap found** is added to the "Known gaps" cell and to section 4 if it is a document case, then fixed and tested before moving on.
- **Daily end:** push to a branch, update status marks here, list what was not verified.
- **Deploy:** only from `main`, only after the tests are green; the live servers always run what is on `main`.

## 6. Suggested first week

1. Put the live servers on `main` (so we work on what really runs).
2. **A1, A4** (intake and worker): watchdog, alerts, mail from every sender kind, auto-reply handling.
3. **A3, A5** (coordinator and notifications): the "stuck too long" sweep; no silent outcome; who is told when nobody can be.
4. **B3, B5, B7** (vendor, PO, invoice): close every row in section 4 marked `GAP`, `PART` or `CHECK`.
5. Tester: browser tests for every row of section 4.
6. Then **D4, D5, D3** (security, servers, backups) and sign-off for go-live.
