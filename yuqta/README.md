# Yuqta — POC V0.1

Enterprise business intelligence: **Meeting → Intelligence → Action**.

Target flow: Meeting → Transcript → Understand → Correlate with business data → KPI → RCA → Dashboard → Recommendations.

**Status: the full POC flow works end to end**, with real-provider integrations behind environment variables:

- **Meeting in:** **Yuqta joins a live call** as a notetaker bot (mock or **Recall.ai**), sample meeting, audio upload (mock STT or **Deepgram**), or **Google Meet transcript import** (mock or live Google).
- **Understand:** mock rules or **Claude** (Anthropic API) extract business signals.
- **Then:** checked against revenue/orders/renewals → KPIs → revenue root cause → dashboard → recommended actions.
- **Access:** optional login page and API service token.

Everything runs with no keys (all providers default to `mock`).

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Recharts |
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 |
| Runtime | Docker Compose |

## Architecture

The POC is a **deterministic workflow**. There are no autonomous agents in V0.1.

| Concept | Folder | Meaning |
| --- | --- | --- |
| Connectors | `backend/app/connectors` | External systems (Google Workspace, CRM, ERP) |
| Plugins | `backend/app/plugins` | Reusable capabilities behind provider interfaces (STT, LLM) |
| Deterministic services | `analytics`, `processing`, `dashboard`, `db` | KPI, RCA, persistence, dashboard specs |
| Workflows | `backend/app/workflows` | Fixed pipelines that call the services above |
| Agents | *(future)* | Will orchestrate the same workflows and services without changing them |

External providers default to `mock`. No API keys are needed.

```
yuqta/
├── backend/          FastAPI app, Alembic migrations, tests, Dockerfile
├── frontend/         Next.js app (app/, components/, lib/), Dockerfile
├── data/             seed.sql (demo business data), sample_transcript.json
├── docker-compose.yml
├── .env.example
└── Makefile
```

## Run with Docker (recommended)

Prerequisite: Docker Desktop is running.

```bash
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
docker compose up --build -d
docker compose ps             # all three services should be "healthy" / "running"
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| Backend health | http://localhost:8000/health |
| Meetings UI (sample + audio upload) | http://localhost:3000/meetings |
| Google Meet import UI | http://localhost:3000/import |
| Dashboard UI | http://localhost:3000/dashboard |
| Customers | http://localhost:8000/api/customers |
| API docs | http://localhost:8000/docs |
| PostgreSQL | `localhost:5433`, user/password/db `yuqta` |

Postgres is published on **5433**, not 5432, so it does not clash with a local Postgres install. If any host port is taken, change `POSTGRES_HOST_PORT`, `BACKEND_HOST_PORT` or `FRONTEND_HOST_PORT` in `.env`.

Check health:

```bash
curl http://localhost:8000/health
# {"status":"ok","app_env":"development","database":"ok"}
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness plus database status |
| GET | `/api/customers` | Seeded customers with renewal status |
| POST | `/api/meetings/sample` | Create **Enterprise Revenue Review** by running the STT plugin (mock returns `data/sample_transcript.json`) |
| POST | `/api/meetings/audio` | Upload a recording (multipart: `file`, `title`, `participants`); transcribed by the configured STT provider |
| POST | `/api/meetings` | Create a meeting from transcript segments you supply (`title`, `participants`, `segments[{speaker, text, start_seconds, end_seconds}]`) |
| GET | `/api/meetings` | List meetings (newest first) with segment counts |
| GET | `/api/meetings/{id}` | One meeting with its transcript segments |
| POST | `/api/meetings/{id}/analyze` | Understand → correlate → KPI → RCA; stores results, sets status `analyzed`. Re-running replaces earlier results |
| GET | `/api/meetings/{id}/analysis` | The stored analysis, including recommendations (404 until analyzed) |
| GET | `/api/meetings/{id}/dashboard` | The meeting's dashboard spec (404 until analyzed) |
| GET | `/api/dashboard/latest` | The dashboard updated by the most recent analysis |
| POST | `/api/bots` | Send the Yuqta notetaker into a live call (`meeting_url`: Google Meet, Zoom or Teams link; optional `title`) |
| GET | `/api/bots` | Recent bots with their status (`scheduled` → `joining` → `waiting` → `recording` → `processing` → `analyzed`, or `failed` / `cancelled`) |
| POST | `/api/bots/check` | Check active bots now instead of waiting for the background poll |
| POST | `/api/bots/{id}/leave` | Make the bot leave; what it recorded is still transcribed and analyzed. A `scheduled` bot is cancelled instead |
| GET | `/api/bots/calendar` | Calendar auto-join state: enabled, Google connection, last run, recent changes |
| POST | `/api/bots/calendar/sync` | Read the calendar now and schedule, reschedule or cancel bots (409 when `AUTO_JOIN_CALENDAR=false`) |
| GET | `/api/history` | Recent meetings (`limit`, default 100) with all their action items, decisions, risks and open questions in one place |
| GET | `/api/system` | Active providers and upload limit (never keys) |
| GET | `/api/google/status` | Connector mode and connection state |
| POST | `/api/google/connect` | Returns the Google sign-in URL (mock mode: straight to the callback) |
| GET | `/auth/google/callback` | Public OAuth redirect target; accepts only a state issued by `/connect` |
| POST | `/api/google/disconnect` | Revokes and forgets the connection |
| GET | `/api/google/auto-import` | Auto-import state and recent imports |
| POST | `/api/google/auto-import/run` | Check for finished meetings now |
| POST | `/api/google/auto-import/simulate` | Mock mode only: simulate a meeting ending |
| GET | `/api/google/events` | Recent Calendar events that have a Meet call |
| GET | `/api/google/conference-records` | Meet calls for a meeting code, with transcript status |
| POST | `/api/google/import` | Imports a Meet transcript as a Yuqta meeting (source `google_meet`) |

When `API_AUTH_TOKEN` is set, every `/api/*` route requires `Authorization: Bearer <token>`; `/health` and the OAuth callback stay public.

Ingestion is a fixed workflow (`app/workflows/ingest_meeting.py`): create meeting → transcribe (STT plugin) → normalise segments (`app/processing`) → store → status `transcribed`. If transcription fails, the meeting is kept with status `failed` and the API returns 502.

```bash
curl -X POST http://localhost:8000/api/meetings/sample
curl http://localhost:8000/api/meetings
```

The sample meeting always uses the fixture transcript. Uploaded audio uses `STT_PROVIDER`: `mock` returns the fixture transcript; `deepgram` sends the audio to Deepgram's pre-recorded API (`model=nova-3`, speaker diarization, utterances) and stores one segment per utterance, labelled "Speaker 1", "Speaker 2", ….

### Meeting-first analysis

Every meeting gets its own intelligence, whatever it is about: a summary, meeting type, topics, decisions,
action items (owner and due date as said), risks, open questions and who spoke how much. Each item quotes
the transcript line it came from. The steps below (correlate, KPI, RCA) run **only when business data is
loaded and the meeting discusses a known customer or revenue**; otherwise the dashboard shows the meeting
alone ("Next steps" instead of revenue recommendations).

`DEMO_BUSINESS_DATA=true` (default) loads the demo customers Acme, Beta and Gamma into an empty database.
With `false` nothing is loaded; `python -m app.db.seed --clear` removes business data already loaded, and
`python -m app.db.seed` loads `data/seed.sql` (your own data, once you replace the demo rows).

### Analysis (Phase 4)

`app/workflows/analyze_meeting.py` runs a fixed sequence:

1. **Understand** - the `LLMProvider` plugin (`app/plugins/llm`) turns the transcript into structured signals, each quoting its source line. `LLM_PROVIDER=openrouter` uses **Jev** (`LLM_MODEL=typesafe/jev-router`, the default model) through OpenRouter, sending the signal schema as a strict JSON-schema response format; any other OpenRouter model with structured outputs also works. `LLM_PROVIDER=mock` is a deterministic rule-based extractor for offline use. `LLM_PROVIDER=anthropic` (optional) calls Claude through the official Anthropic SDK and needs a `claude-*` model id. Model output is treated as untrusted: quotes are always taken from the transcript, and customers not in the business data are dropped.
2. **Correlate** (`app/analytics/correlation.py`) - each signal is checked against the business data and marked `confirmed`, `contradicted` or `no_data`.
3. **KPI** (`app/analytics/kpi.py`) - revenue, order volume and renewal status for what was discussed.
4. **RCA** (`app/analytics/rca.py`) - the revenue change split by account, with drivers from orders and renewals, and whether each account was discussed in the meeting.

For the sample meeting:

> Revenue down $440K (−18.4%). Acme (−$190K) and Beta (−$120K), discussed in the meeting, explain 70.5% of the decline. Not discussed: Gamma (−$80K).

Results are stored in `meeting_insights` (one `summary` row plus `signal`, `kpi`, `root_cause` and `recommendation` rows).

### Dashboard and recommendations (Phase 5)

The same workflow continues:

5. **Recommendations** (`app/analytics/recommendations.py`) - fixed rules turn the analysis into prioritised actions with an owner (the account owner), a due date when the meeting agreed one, the reasoning and the quotes behind it. For the sample: contact Acme (high, Rahul, this week), escalate Beta's overdue renewal (high, Priya, this week), review Gamma's undiscussed decline (medium, Amit), review long-tail accounts (low).
6. **Dashboard** (`app/dashboard/spec.py`) - a JSON *dashboard spec* (summary, KPIs, two bar charts with their data, recommendations) stored in `dashboard_specs`. The frontend draws whatever the spec contains, so the backend owns what the dashboard shows.

Re-running the analysis replaces the meeting's insights and dashboard. Deleting a meeting deletes its dashboard.

```bash
curl -X POST http://localhost:8000/api/meetings/<id>/analyze
```

## Real providers and login

All optional. Set them in `.env`, then `docker compose up -d`.

| Feature | Settings | Notes |
| --- | --- | --- |
| Jev (default LLM) | `LLM_PROVIDER=openrouter`, `LLM_API_KEY=sk-or-...` (`LLM_MODEL=typesafe/jev-router` is the default) | Jev Router picks the underlying model per request; Yuqta sets `require_parameters` so OpenRouter only routes to providers that support structured outputs. Billed by OpenRouter. Any other `vendor/model` id with structured outputs also works. |
| Claude (optional) | `LLM_PROVIDER=anthropic`, `LLM_API_KEY=sk-ant-...`, `LLM_MODEL=claude-opus-5-5` (optional `LLM_EFFORT`) | Billed by Anthropic. |
| Deepgram transcription | `STT_PROVIDER=deepgram`, `DEEPGRAM_API_KEY=...` (optional `DEEPGRAM_MODEL`, `STT_LANGUAGE`) | Upload audio/video up to `MAX_AUDIO_MB` (200). |
| Real Google Meet | `GOOGLE_MODE=live`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Enable Calendar API and Meet REST API; OAuth client type "Web application" with redirect URI `http://localhost:8000/auth/google/callback`; scopes `calendar.events.readonly` and `meetings.space.readonly`. Tokens are kept in backend memory only (reconnect after a restart). |
| Login | `APP_PASSWORD`, `API_AUTH_TOKEN`, `AUTH_SECRET` (and `AUTH_COOKIE_SECURE=true` behind HTTPS) | One shared workspace password. The service token is only used server-side by the frontend. |

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

### Live meetings: Yuqta joins the call

On **Meetings → Invite Yuqta to a live meeting**, paste a Google Meet, Zoom or Teams link. A participant called
**Yuqta Notetaker** (`BOT_NAME`) joins the call; the host clicks **Admit** like for any guest. It records who says
what (speaker names come from the meeting). When the call ends (or you click **End recording**), Yuqta imports the
transcript as a meeting (source `recall_bot`), analyzes it and updates the dashboard with no clicks.

A background worker checks active bots every `BOT_POLL_SECONDS` (15), so no public URL or webhook is needed. Each
call is imported once (`meetings.external_ref`). Bot state lives in the `meeting_bots` table and survives restarts.

| Setting | Meaning |
| --- | --- |
| `MEETING_BOT_PROVIDER=mock` | Default. A simulated bot "attends" for about 30 s and returns the sample meeting. |
| `MEETING_BOT_PROVIDER=recall`, `RECALL_API_KEY`, `RECALL_REGION` | Real bot via [Recall.ai](https://www.recall.ai) (paid per recording hour; transcription by Recall.ai). Works with personal Gmail meetings, unlike Google's own transcripts. Use the region of your Recall workspace (`us-west-2` for pay-as-you-go). |

Notes: someone must admit the bot (a waiting room times out after about 20 minutes), the bot cannot join meetings
that only allow signed-in users of an organisation, and tell participants that the meeting is being recorded.

#### Calendar auto-join

With `AUTO_JOIN_CALENDAR=true`, Yuqta sends the bot to every Google Meet on the connected Google Calendar, so
nobody has to paste links. A background worker reads the next `AUTO_JOIN_HOURS_AHEAD` (24) hours every
`AUTO_JOIN_POLL_SECONDS` (120) and, per Meet event:

- schedules a bot (status `scheduled`) to join a minute before the start — Recall.ai guarantees on-time joining
  for bots scheduled more than 10 minutes ahead — or sends one right away if the meeting has already started;
- reschedules it when the event moves, and cancels it when the event is deleted or you decline it;
- skips all-day events, declined events and events without a Meet link.

Each event gets at most one bot, and bots within 10 minutes of joining (or already in the call) are never touched.
The **Live meetings** panel shows the auto-join state, the last changes and a **Check calendar now** button;
scheduled bots can be cancelled there. Needs **Connect Google** on the Import page (reconnect after a backend
restart); with `GOOGLE_MODE=mock` it runs against the fake calendar.

### Meeting history

**History** (`/history`, API `GET /api/history`) puts what all meetings produced side by side: totals, every
action item (owner and due date), decision, risk and open question with the meeting and quote it came from, and
who owns the most actions. It reads the stored analysis only, so it never calls the LLM. Meetings analyzed before
meeting-first analysis are listed with zero counts — re-run their analysis to fill them in.

### Automatic import of finished meetings

When a Google Meet call ends and Google generates its transcript, Yuqta imports it (title and attendees from the matching Calendar event), analyzes it and updates the dashboard with no clicks. Google sends a "transcript ready" event ([Workspace Events API](https://developers.google.com/workspace/events/guides/events-meet)) to a Pub/Sub topic; a background worker pulls it every `AUTO_IMPORT_POLL_SECONDS` (15), so Yuqta needs no public URL. Events are acknowledged only after processing; a transient failure is retried, and a meeting is never imported twice.

Setup (Google Cloud Console, your project):

1. Enable **Google Workspace Events API** and **Cloud Pub/Sub API**.
2. **Pub/Sub → Topics → Create topic** `yuqta-meet-events` (uncheck "Add a default subscription").
3. On the topic: **Permissions → Add principal** `meet-api-event-push@system.gserviceaccount.com` with role **Pub/Sub Publisher**.
4. **Pub/Sub → Subscriptions → Create subscription** `yuqta-meet-events-sub`, delivery type **Pull**, on that topic.
5. **Google Auth Platform → Data Access → Add scope** `https://www.googleapis.com/auth/pubsub`.
6. In `.env`: `GOOGLE_MODE=live`, `GOOGLE_PUBSUB_TOPIC=projects/<project-id>/topics/yuqta-meet-events`, `GOOGLE_PUBSUB_SUBSCRIPTION=projects/<project-id>/subscriptions/yuqta-meet-events-sub`; then `docker compose up -d` and **Connect Google** on the Import page (reconnect after each backend restart).

Requirements: the account must be able to record Meet transcripts (a Google Workspace edition with transcription; personal Gmail accounts usually cannot), transcription must be turned on in the call, and transcripts arrive a few minutes after the call ends. In mock mode the Import page has **Simulate a finished meeting** to exercise the same pipeline.

In mock mode, the Google connector serves a fake Calendar and Meet (an "Enterprise Revenue Review" call yesterday with a transcript, a standup without one) through the same client code the live mode uses.

## Database and demo data

On startup the backend container runs `alembic upgrade head` and then loads `data/seed.sql` **only if the database is empty**. Restarts never overwrite data.

| Table | Contents |
| --- | --- |
| `customers` | C001 Acme (Retail, Rahul, At Risk), C002 Beta (Technology, Priya, At Risk), C003 Gamma (Manufacturing, Amit, Healthy) |
| `revenue` | Monthly revenue per customer; `customer_id` NULL = long-tail "Other" |
| `orders` | Orders with units and amount |
| `renewals` | Contract renewals with status `upcoming` / `renewed` / `overdue` / `churned` |
| `meetings`, `transcript_segments` | Filled by the ingestion workflow (Phase 3) |
| `meeting_insights` | Analysis results and recommendations |
| `meeting_bots` | Notetaker bots sent into live calls, their status and the meeting they produced |
| `dashboard_specs` | One dashboard spec per analyzed meeting |

Demo figures (previous month = Aug 2026, current month = Sep 2026):

| | Aug 2026 | Sep 2026 | Change |
| --- | ---: | ---: | ---: |
| Acme | $820K | $630K | −$190K |
| Beta | $540K | $420K | −$120K |
| Gamma | $610K | $530K | −$80K |
| Other | $420K | $370K | −$50K |
| **Total** | **$2.39M** | **$1.95M** | **−$440K (−18.4%)** |

Acme order volume is 1,000 → 690 units (−31%). Beta's renewal is overdue.

```bash
docker compose exec backend python -m app.db.seed              # reset demo business data (meetings untouched)
docker compose exec backend alembic current                     # show applied migration
docker compose exec postgres psql -U yuqta -d yuqta             # SQL shell
```

New migration after changing `backend/app/db/models.py`:

```bash
docker compose run --rm backend alembic revision --autogenerate -m "describe change"
docker compose run --rm backend alembic upgrade head
```

Stop:

```bash
docker compose down        # keep data
docker compose down -v     # also delete the database volume
```

With `make` installed, `make up`, `make down`, `make test`, `make test-db` and `make health` wrap the commands above.

## Tests

Inside Docker:

```bash
docker compose run --rm --no-deps backend python -m pytest -q                # unit tests
docker compose run --rm -e RUN_DB_TESTS=1 backend python -m pytest -q        # + real Postgres checks
```

Locally (from `backend/`, in a virtual environment):

```bash
pip install -r requirements.txt
python -m pytest -q
```

Database tests are skipped unless `RUN_DB_TESTS=1` is set and `DATABASE_URL` points at a reachable, migrated Postgres. The seed figures are also checked without a database by parsing `data/seed.sql`.

## Run without Docker (development)

Start only the database in Docker, then run the apps on your machine:

```bash
docker compose up -d postgres

# Backend (terminal 1, from backend/)
#   bash:        export DATABASE_URL=postgresql://yuqta:yuqta@localhost:5433/yuqta
#   PowerShell:  $env:DATABASE_URL = "postgresql://yuqta:yuqta@localhost:5433/yuqta"
alembic upgrade head
python -m app.db.seed --if-empty
python -m uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2, from frontend/)
npm install
npm run dev          # http://localhost:3000, calls the backend at http://localhost:8000
```

The frontend reads the backend URL from the server-side variable `API_INTERNAL_URL`, which defaults to `http://localhost:8000`. Compose sets it to `http://backend:8000`.

> **Windows note:** if `import sqlalchemy` fails with *"An Application Control policy has blocked this file"*, Windows is blocking SQLAlchemy's compiled extension. Reinstall it as pure Python:
> PowerShell: `$env:DISABLE_SQLALCHEMY_CEXT=1; pip install --force-reinstall --no-deps --no-binary sqlalchemy "sqlalchemy>=2.0,<3.0"`.
> Docker is unaffected.

## Keeping secrets out of git

`.env` holds your API keys and is git-ignored. As a second safety net, enable the pre-commit hook once per clone
(from the repository root):

```bash
git config core.hooksPath .githooks
```

It refuses any commit that contains an `.env` file, a value from your local `.env`, or a recognisable API or
private key (OpenRouter, Anthropic, AWS, Google, GitHub). Never bypass it with `--no-verify`; remove the secret instead.

## Configuration

All configuration comes from environment variables (see `.env.example`). Secrets are never hard-coded, and `.env` is git-ignored.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | `development` / `test` / `production` |
| `DATABASE_URL` | — | Postgres URL; `postgresql://` is mapped to the psycopg 3 driver |
| `STT_PROVIDER` | `mock` | `mock` now; `deepgram` later |
| `LLM_PROVIDER` | `mock` | `mock` until a real provider is configured |
| `GOOGLE_MODE` | `mock` | `mock` or `live` |
| `MEETING_BOT_PROVIDER` | `mock` | `mock` or `recall` (needs `RECALL_API_KEY`) |
| `DISPLAY_TIMEZONE` | `UTC` | IANA time zone for times shown in the app and in bot messages, e.g. `Asia/Kolkata` (shown as IST) |

## Roadmap

1. **Foundation** (done): repo, Compose, Postgres, FastAPI health, Next.js home page, tests.
2. **Data layer** (done): SQLAlchemy models, first Alembic migration for all 8 tables, `data/seed.sql` demo data, `GET /api/customers`.
3. **Meeting ingestion** (done): `STTProvider` interface + mock provider, transcript normalisation, ingestion workflow, meetings API, meetings list and transcript pages.
4. **Understand, correlate, KPI, RCA** (done): `LLMProvider` interface + mock provider, correlation, KPI and RCA services, analysis workflow and API, analysis view on the meeting page.
5. **Dashboard and recommendations** (done): rule-based recommendations, dashboard spec, `/dashboard` page with Recharts charts.

6. **Integrations and access** (done): Claude LLM provider, Deepgram STT with audio upload, Google Meet connector (mock + live), login page and API service token.
7. **Live meetings** (done): Yuqta notetaker bot (mock + Recall.ai) joins calls; finished calls are transcribed, analyzed and put on the dashboard automatically.

Possible next steps (not started): per-user accounts instead of one shared password, encrypted persistent storage for the Google connection, and an agent layer that calls the existing workflows.
