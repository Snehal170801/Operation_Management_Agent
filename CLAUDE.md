# Operation Agents (CLAUDE.md)

A procure-to-pay system where AI agents run the whole flow automatically and a person steps in only for approvals and
exceptions. Backend: FastAPI + SQL Server (pyodbc). Frontend: React 19 + TypeScript + Tailwind v4 (Vite). Read this file
first; `README.md` has the longer description of auth and access control.

## Run it (Windows)

Backend, from `backend/`:
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env                 # fill in values; JWT_SECRET must be a long random string
python -m scripts.migrate              # create / upgrade the database schema (safe to repeat)
python -m scripts.create_user you@company.com --role admin
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000      # add --reload while developing
```
Frontend, from `frontend/`:
```
npm install
npm run dev          # http://localhost:5180  (port is fixed; the API is expected on :8000 of the same host)
npm run build        # tsc -b && vite build  -> must pass before you call a change done
npm run lint         # oxlint
```
API docs: http://localhost:8000/docs. Health: `GET /health`. Database: SQL Server Express `localhost\SQLEXPRESS`,
database name from `SQL_DATABASE` in `backend/.env`.

## Test it

```
cd backend && python -m pytest -q            # ~930 tests, no database or network needed
python -m pytest tests/test_my_work.py -q    # one file
```
- Tests need no `.env` (`tests/conftest.py` sets dummies) and **stub the database, email and AI**. A green suite does not
  prove the real database, SMTP, IMAP or Azure OpenAI path works: for anything touching those, also check against the
  running app.
- Frontend has no unit tests; verify UI changes in a real browser (Playwright with the system Chrome works) at desktop
  (1440) and phone (390) widths, and check for horizontal scrolling.
- Every new feature gets tests, **including the failure cases** (see `tests/test_failures.py` for the pattern).
- Before saying "done": `pytest` green, `npm run build` clean, and say plainly what was NOT verified.

## Where things live

```
backend/app/
  api/routes/      thin HTTP routes; permission guards via require_permission(...)
  controllers/     request -> use-case glue
  agents/          one module per agent (purchase, procurement, vendor, approval, PO, delivery, invoice, notification, operations)
  orchestrator/    case_pipeline.py = the ONLY place that sequences agents; worker.py = background loops
  repositories/    all SQL (pyodbc). Numbered migrations in backend/migrations/
  core/            config, permissions, access, escalation/health policies, tunables, request_guard, heartbeat
  clients/         email (SMTP/IMAP), Azure OpenAI, Twilio/Exotel
backend/scripts/   migrate, create_user, seed_*, preflight (check setup), watchdog (alerts if the server is down)
frontend/src/
  app/ (router, providers)   components/ui, components/layout   features/<domain>/ (types, api, hooks, pages, components)
  lib/ (api-client, http, time)
```

## Rules that must hold

- **Agents never call each other.** `orchestrator/case_pipeline.py` passes data between them.
- **Automation first:** add a human gate only for risk (amount limit, unreliable supplier, fewer than 2 quotes, daily
  spend cap, invoice mismatch, stalled case). Limits are env-configurable and adjustable in Settings -> Configure
  (`core/tunables.py` lists what may be changed there; secrets never).
- **Security is enforced on the server.** Hiding a button is not access control. Requesters (`cases:read`) see only their
  own cases and a sanitised timeline (no prices, suppliers, reasons). Unknown/foreign case -> 404, not 403. Never trust a
  name from the request body for who did something: use the signed-in user.
- **No self-approval** and no deciding an invoice for goods you confirmed (`core/separation.py`).
- Pure policy functions (`core/*_policy.py`, `my_work.py`, `escalation.py`) take the clock and data as arguments: keep them
  free of DB access so they stay easy to test.
- Errors: raise the named exceptions in `core/exceptions.py` (mapped to status codes in `core/error_handlers.py`).
  `core/request_guard.py` is the last net (JSON 500 + `request_id`, 503 when the database is unreachable). Retry only
  failures that can pass by themselves (`core/retry.py`); never retry a refusal or a wrong password.
- Vendors are contacted by **email only**. The phone-call feature is built but stays OFF (`CALL_AFTER_EMAIL=false`); do not
  switch it on or add WhatsApp/SMS unless asked.

## Gotchas

- Run `sqlcmd` with `-I` (quoted identifiers) and `-C` (trust the server certificate).
- Start **one** API process at a time: several at once queue on the same database rows and take minutes to start.
- The backend does not reload itself unless started with `--reload`; restart it after code or `.env` changes.
- Windows Git Bash: heredocs that mix quote types break. Use the editor/Write tools for multi-line files, not `cat <<EOF`.
- This machine is slow and short of memory: imports and test runs can take minutes; background servers get stopped.
- The project folder lives inside OneDrive, which can slow file operations (git, npm, test runs).
- Several Claude sessions may edit this repo at once. Check `git status`/`git diff` before editing a file you did not
  start, and keep to your own area.

## Secrets and data

- `backend/.env` and any passwords file are never committed (see `.gitignore`); only `.env.example` is. Never paste real
  tokens into chat, commits or docs. If one leaks, rotate it.
- Seed scripts create demo accounts with a default password (`Admin@123`). Change them before any real use.
- Before real use: change all default passwords, set `ENVIRONMENT=production`, `COOKIE_SECURE=true`, restrict
  `CORS_ORIGINS`, set `ALLOW_OPEN_ACCOUNT=false`, use HTTPS, and run the server as a service that restarts itself.

## Git

- One repository (`cognexa-cx/operation-agents`, private); `main` is the default branch. Work on a branch, keep commits
  small and focused, and write messages that say why. Do not commit `.env`, passwords, `node_modules` or `dist`.
- Do not push, force-push or rewrite history unless asked.
