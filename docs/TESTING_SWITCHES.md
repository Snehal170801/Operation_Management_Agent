# Test-only switches

Two switches let automated end-to-end tests run the real app without real email, the real AI, or real data.

| Switch | What it does |
|---|---|
| `TEST_MAIL_DIR=<folder>` | Emails the app "sends" are written to `<folder>/outbox/*.json` instead of going to SMTP. Supplier replies are dropped into `<folder>/inbox/` and read by the normal mailbox reader (including the "wait for new mail" loop). Read messages move to `<folder>/inbox/processed/`. |
| `TEST_AI_STUB=true` | Every AI call is answered by fixed rules in `app/clients/ai_stub.py` (no network, no cost, same answer every time). |

## The safety guard

`app/core/config.py` refuses to load (so the API, the worker and the scripts all refuse to start) when either switch is on and any of these is true
(`app/core/test_switches.py`):

- `ENVIRONMENT` is `production`
- `SQL_DATABASE` does not end in `_test`
- `CALL_AFTER_EMAIL` is on

So the switches can never be combined with the real database, and a real database can never be run with fake email or a fake AI by accident.

## Using them

Run the test servers with their own database and ports, with real mail and AI settings blanked. Environment variables set in the process win over
`backend/.env` (`load_dotenv` does not override), so blank values are enough:

```
SQL_DATABASE=opetional_agents_test
TEST_MAIL_DIR=C:\path\to\test-mail
TEST_AI_STUB=true
SMTP_HOST=            IMAP_HOST=            (blank: nothing can reach a real mailbox)
AZURE_OPENAI_API_KEY= AZURE_OPENAI_ENDPOINT=
CALL_AFTER_EMAIL=false
APP_BASE_URL=http://localhost:5190         CORS_ORIGINS=http://localhost:5190
```

Create the database and tables with `python -m scripts.migrate` (with `SQL_DATABASE` set as above), then start uvicorn on a port other than 8000/8001,
for example `python -m uvicorn app.main:app --port 8100`. Never run it on the ports the real servers use.

### From a test (TypeScript or Python)

- **Read what the app sent:** read the JSON files in `<TEST_MAIL_DIR>/outbox/`. Each has `to`, `subject`, `body`, `html`, `sent_at`. An approval email's
  `body` contains the `/decide/<token>?a=approve` link.
- **Play a supplier:** write a JSON file into `<TEST_MAIL_DIR>/inbox/` with `from_email`, `subject` and `body` (optional `attachments`: `[{"name", "text"}]`).
  The subject must carry the case tag the app put in its email (reply with `Re: <the original subject>`), otherwise the message is ignored, exactly as
  with real mail. A message from `mailer-daemon@...` is read as a bounce. Write the file under a temporary name and rename it so the app never reads half a file.
- **From Python:** `app.clients.test_mailbox` has `read_outbox(dir, to=None, subject_contains=None)`, `drop_inbound(dir, from_email, subject, body)` and
  `reply_to(dir, sent_entry, body)`.

### What the AI stand-in understands

- **A purchase request:** reads "Need 8 steel storage racks, urgent, needed by 2026-10-20" as 8 x "steel storage racks", urgent, needed by that date.
  To control it exactly, start the text with `TESTJSON:` followed by the JSON the Purchase Agent should return, for example
  `TESTJSON: {"items": [{"description": "Steel rack", "quantity": 8}], "cost_center": null}`.
- **Supplier quotes:** `Total Rs 42,000. Delivery 7 days. Terms: 50% advance` (also `₹` or `INR`; "valid 10 days" sets validity).
- **Ranking:** cheapest first, with a reason per supplier.
- **Replies to an order:** "confirm / received your order" = confirmed; "cannot / sorry" = problem; "new price 99,000" = price change; "already shipped" = cancellation refused.
- **Invoices:** text starting `Invoice INV-77. PO-1005. 8 x Steel rack. Total Rs 70,000.`
- **Stock matching:** never guesses; only same-product wording matches a stock row.
- An unknown prompt raises an error, so a new AI call added to the app fails loudly in tests until the stub learns it.

## Tests for this

`backend/tests/test_test_switches.py` (guard rules, a real refusal-to-start check in a subprocess, the mailbox, the AI stub, and a run through the pipeline).
