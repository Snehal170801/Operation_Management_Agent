# Operation Agents

Procure-to-pay case management driven by AI agents.

```
backend/            FastAPI service
  app/
    api/routes/     HTTP routes (thin)
    controllers/    request -> use-case glue
    orchestrator/   sequencing of agents per case
    agents/         operations, purchase, procurement, vendor
    repositories/   SQL access (pyodbc)
    models/         Pydantic schemas
    clients/        external clients (Azure OpenAI)
    core/           config, logging, exceptions, error handlers
    db/             connection
  migrations/       numbered SQL scripts, run in order
  tests/
frontend/           React + TypeScript + Tailwind v4 (Vite)
  src/
    app/            App, providers, router
    components/     ui/ (Badge, Card, QueryState), layout/ (AppShell)
    features/       one folder per domain: types, api, hooks, pages, components
      cases/  purchase-requests/  stock/  vendors/
    lib/            api-client, formatting helpers
    pages/          generic pages (404)
legacy_frontend/    old static test page, delete once React reaches parity
docs/
```

## Backend

```
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env      # then fill in values (incl. a random JWT_SECRET)
python -m scripts.migrate                          # create/upgrade the schema
python -m scripts.create_user admin --role admin   # first admin (prompts for password)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pytest
```

API docs: http://localhost:8000/docs

## Frontend

```
cd frontend
npm install
copy .env.example .env.development   # VITE_API_BASE_URL
npm run dev                          # http://localhost:5180
npm run build
```

## Auth and access control

- **Sessions:** short-lived (15 min) access JWT held in browser memory + a rotating refresh token in an
  httpOnly cookie, stored hashed in `RefreshTokens`. Logout revokes the whole session family; replaying a used
  refresh token revokes it too. Five failed sign-ins lock an account for 15 minutes.
- **Access is set per user, with checkmarks (no roles screen).** On **Users -> Add / Edit**, each area
  (Cases, Stock, Vendors, Approvals, Users, ...) has two ticks: **Read only** or **CRUD** (CRUD includes Read
  only; Cases also has "Own only" for requesters), plus an **Administrator** switch (full access, can manage users).
  - `backend/app/core/permissions.py` defines the areas, their ticks ("levels") and the `resource:action`
    permissions each tick grants. Routes check those permissions. To add an area: add it there and guard a route.
  - Each non-admin user's ticks are stored as a private permission set named `u_<id>` (tables `Roles` /
    `RolePermissions`, never shown as roles). That keeps one permission-checking path for the whole API.
  - The access token only identifies the user. Their active flag and current permissions are looked up live
    (cached ~15 s, dropped on every change), so ticking/unticking or deactivating takes effect within seconds.
  - No privilege escalation: you can't tick anything you don't hold yourself, only an admin can make or remove
    an admin, you can't edit/reset someone with more access than you, and you can't remove your own
    `users:write` or your own admin access. The last active admin is protected.
  - Alert emails go to everyone who can approve orders (Approvals CRUD) and to admins.
- **Audit log** (`/audit`, **Audit Log** page): sign-ins (success/failure/lock), logouts, token-reuse, password
  changes/resets, user and access changes, and every `authz.denied`. Secrets (passwords, codes, tokens) are
  redacted before they are written. Writing an audit row never breaks the action being audited.
- **Admin tools:** Users, Audit Log and Settings -> System Health, each behind its own tick.
- **Sign-in is by email.** Create users with an email (Users page, or
  `python -m scripts.create_user you@example.com --role admin`).
- **Forgot password:** emails a 6-digit code (valid 10 min, 5 tries, 60 s between sends, 5 per hour). The
  endpoint answers identically whether or not the account exists. Mail goes through `SMTP_*` in `.env`; with
  `SMTP_HOST` empty it is only logged (dry run, development only; in production nothing is logged or sent).
- **Going to production:** serve over HTTPS and set `COOKIE_SECURE=true`, set `ENVIRONMENT=production`,
  use a unique `JWT_SECRET`, restrict `CORS_ORIGINS` to the real frontend origin, and change the seeded
  admin password.

## Demo phone calls (Exotel)

The Calling Agent rings a phone through Exotel and connects it to a call flow you built in the Exotel dashboard
(the spoken content lives in that flow; this demo does not hold an AI conversation).

1. In Exotel: verify your number, note your ExoPhone (my.exotel.com/numbers) and the id of the flow you want to run.
2. In `backend/.env` set `EXOTEL_ACCOUNT_SID`, `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN` (Settings -> API Settings),
   `EXOTEL_FROM_NUMBER` (your ExoPhone) and `EXOTEL_APP_ID` (or `EXOTEL_CONNECT_TO` to dial a second number).
   Set `CALL_ALLOWED_NUMBERS` to the numbers that may be rung. Restart the backend.
3. Sign in at http://localhost:8000/docs, Authorize, and call `POST /calls` with
   `{"to": "+919325642310", "case_id": "<optional case id>"}`.

## "Please check your email" calls (Twilio)

After the system emails a vendor (a request for quotation, or a purchase order), the Calling Agent can ring that
vendor and say, in Hindi, Marathi or English, that details were sent to their email. The orchestrator triggers it;
agents never call each other. A failed or skipped call never blocks the case: a `call.skipped` event with the
reason is added to the case timeline instead.

Setup (all four are needed):

1. Upgrade the Twilio account to a paid one. A free trial cannot speak custom text.
2. In `backend/.env` leave `TWILIO_ANSWER_URL=` empty (the trial template would override the message) and set
   `CALL_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`.
3. Set `CALL_AFTER_EMAIL=true`. Optional: `CALL_COMPANY_NAME`, `CALL_HOURS_START` / `CALL_HOURS_END` (India time,
   default 9 to 19; nothing is rung outside them), `CALL_VOICE_HI` / `CALL_VOICE_MR` / `CALL_VOICE_EN`.
4. On the Vendors page give each vendor a phone number and the language of the call. Restart the backend.

A vendor is rung once per case for each of RFQ and PO, and not at all while automation is paused. Have a native
speaker listen to the Hindi and Marathi wording (`_MESSAGES` in `app/agents/calling_agent.py`) before real use.
