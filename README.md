# Yuqta Notetaker

**Meeting → Intelligence → Action.** Yuqta joins your Google Meet, Zoom or Teams calls as a notetaker,
transcribes them (English, Hindi and Hinglish), and turns each meeting into a summary, decisions, tasks
with owners and due dates, risks and open questions. The recording and summary are emailed to the
people who registered their Google account.

```
Calendar / meeting link ──▶ Yuqta Notetaker joins ──▶ recording + transcript (Recall.ai)
        ──▶ AI analysis (summary, decisions, tasks, risks, questions)
        ──▶ dashboard + task board + history ──▶ email: recording & summary, minutes, daily reminders
```

## Features

| | |
| --- | --- |
| **Live notetaker** | Paste a meeting link, or let **calendar auto-join** send the bot to every Google Meet on the connected calendars. It posts a recording notice in the chat when it joins. |
| **Multilingual transcripts** | Recall.ai transcription with language `auto` (Hindi/English switching); Deepgram or AWS Transcribe optional. Uploaded recordings use Deepgram `multi`. |
| **Meeting intelligence** | Summary, meeting type, topics, decisions, action items (owner, due date), risks, open questions and who spoke. Every item quotes the transcript line it came from; all output is in English. |
| **Task tracking** | Action items become tasks: Open / In progress / Done, owner, real due date ("by next Wednesday" → a date), views and filters, a daily reminder email. |
| **Recording + summary email** | After each meeting the registered Google accounts get the recording link and the summary. Other attendees get the minutes (no recording) after review or automatically. |
| **History** | All meetings, tasks, decisions, risks and questions in one place. |
| **Business data (optional)** | Load customers, revenue, orders and renewals; when a meeting discusses them, Yuqta checks what was said against the numbers (KPIs, root cause). |

## Quick start

Requirements: **Docker Desktop** (running) and the API keys listed below.

```powershell
git clone https://github.com/Annu-chauhan/yuqta-Notetaker.git
cd yuqta-Notetaker\yuqta
Copy-Item .env.example .env        # bash: cp .env.example .env  — then fill in .env
docker compose up --build -d
docker compose ps                  # postgres, backend, frontend should be running/healthy
```

| | |
| --- | --- |
| App | http://localhost:3000 |
| API health | http://localhost:8000/health |
| API docs | http://localhost:8000/docs |
| PostgreSQL | `localhost:5433`, user / password / db `yuqta` |

Everything also runs **without any keys** (all providers default to `mock`), which is useful to try the UI.

## Configuration (`yuqta/.env`)

`.env` holds your keys and is never committed (`.gitignore` and a pre-commit hook block it).
Every setting is explained in [`yuqta/.env.example`](yuqta/.env.example). The ones you need:

| Purpose | Settings | Where to get it |
| --- | --- | --- |
| Meeting bot + transcription | `MEETING_BOT_PROVIDER=recall`, `RECALL_API_KEY`, `RECALL_REGION` (e.g. `us-west-2`) | [recall.ai](https://www.recall.ai) dashboard → API keys |
| AI analysis | `LLM_PROVIDER=openrouter`, `LLM_API_KEY`, `LLM_MODEL` | [openrouter.ai](https://openrouter.ai) → Keys |
| Uploaded recordings | `STT_PROVIDER=deepgram`, `DEEPGRAM_API_KEY`, `STT_LANGUAGE=multi` | [deepgram.com](https://deepgram.com) |
| Google sign-in, calendar | `GOOGLE_MODE=live`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `TOKEN_ENCRYPTION_KEY` | Google Cloud Console (see below) |
| Email (pick one) | **Gmail app password:** `SMTP_HOST=smtp.gmail.com`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` — or **connected Gmail:** `GMAIL_SEND=true` | [App passwords](https://myaccount.google.com/apppasswords) (needs 2-Step Verification) |
| Login (before sharing) | `APP_PASSWORD`, `API_AUTH_TOKEN`, `AUTH_SECRET` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

Generate `TOKEN_ENCRYPTION_KEY` with
`python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`.
It encrypts the saved Google logins so they survive restarts; changing it means reconnecting Google.

After editing `.env`, apply it with `docker compose up -d`.

### Google Cloud setup (for calendar auto-join and sign-in)

1. In [Google Cloud Console](https://console.cloud.google.com) create a project and enable the
   **Google Calendar API**, **Google Meet REST API** and (to send email through Gmail) the **Gmail API**.
2. **Google Auth Platform → Clients → Create client**, type *Web application*, redirect URI
   `http://localhost:8000/auth/google/callback`. Copy the client ID and secret into `.env`.
3. **Data Access → Add scopes:** `calendar.events.readonly`, `meetings.space.readonly`, `gmail.send`.
4. **Audience → Test users:** add every Gmail address that will connect.
5. In Yuqta open **Import → Connect Google**, allow calendar access and (optionally) *Send email on your behalf*.
   Each account shows **✓ can send email** when Gmail sending is allowed.

## Using Yuqta

1. **Meetings** → paste a meeting link (and optionally an *Admin email*) → **Send Yuqta to the meeting**,
   or turn on calendar auto-join (`AUTO_JOIN_CALENDAR=true`) and connect Google.
2. In the call, **admit "Yuqta Notetaker"**. It posts the recording notice in the chat.
3. When the call ends, the status goes Recording → Transcribing → **Analyzed** (a few minutes).
4. Open the meeting for the transcript, analysis, **▶ Watch recording** and the **Minutes email** panel;
   **Dashboard** and **History** show the results and all tasks.

The meeting needs **at least one person speaking**: a call with silence or muted microphones is recorded
but has nothing to summarise, and is marked *failed*.

### Who receives which email

| Email | Recipients | When |
| --- | --- | --- |
| Recording + summary | Every registered Google account that had the meeting on its calendar (main account for bots sent by hand); the organizer or typed admin too if inside your organisation | Right after analysis (`MINUTES_EMAIL=review` or `auto`) |
| Minutes (no recording) | Other calendar attendees + `MINUTES_TO` | `review`: after you click **Send** on the meeting page · `auto`: at once, except outside addresses which wait for approval · `off`: by hand only |
| Daily task reminder | `REMINDER_TO`, else the main registered account | Once a day after `REMINDER_HOUR` (`DISPLAY_TIMEZONE`), only when tasks are due |

The recording link in an email works for about 6 hours (a Recall.ai security limit); the
**Watch recording** page always fetches a fresh one. Recordings are never emailed to outside addresses automatically.

## Everyday commands (run in `yuqta/`)

```powershell
docker compose up -d                 # start (or apply .env changes)
docker compose ps                    # status
docker compose logs -f backend       # live backend logs (Ctrl+C to stop)
docker compose logs --since 10m | Select-String "ERROR|WARNING|Traceback"   # problems only
docker compose down                  # stop, keep data   (down -v also deletes the database)
docker compose exec backend python -m app.db.seed          # load data/seed.sql (business data)
docker compose exec backend python -m app.db.seed --clear  # remove business data (meetings stay)
```

With `make`: `make up`, `make down`, `make test`, `make test-db`, `make health`.

## Architecture

| Layer | Tech |
| --- | --- |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Recharts |
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 |
| Providers | Recall.ai (bot, recording, transcript), OpenRouter / Anthropic (analysis), Deepgram (uploads), Google Calendar / Meet / Gmail |

```
yuqta/
├── backend/app
│   ├── api/          HTTP routes
│   ├── connectors/   meeting_bot (Recall.ai, mock), google (Calendar, Meet, Gmail, mock)
│   ├── plugins/      llm (OpenRouter, Anthropic, mock), stt (Deepgram, mock)
│   ├── workflows/    meeting bots, calendar auto-join, analysis, action items, minutes, reminders
│   ├── analytics/    meeting intelligence, due dates, business KPIs and root cause
│   └── db/           models, seed, encrypted credentials
├── backend/alembic/  database migrations
├── frontend/         Next.js app (app/, components/, lib/)
├── data/             seed.sql (optional demo business data), sample_transcript.json
├── docker-compose.yml, .env.example, Makefile
```

Background workers in the backend: meeting bots (every 15 s), calendar auto-join (every 2 min),
task reminders (every 10 min). Migrations run automatically on startup.

### API

Interactive docs at http://localhost:8000/docs. Main routes:

| Area | Routes |
| --- | --- |
| Health / system | `GET /health`, `GET /api/system` |
| Meetings | `GET/POST /api/meetings`, `POST /api/meetings/audio`, `GET/DELETE /api/meetings/{id}`, `POST /api/meetings/{id}/analyze`, `GET /api/meetings/{id}/analysis`, `GET /api/meetings/{id}/dashboard` |
| Recording & minutes | `GET /api/meetings/{id}/recording`, `GET /api/meetings/{id}/minutes`, `POST /api/meetings/{id}/minutes/send` |
| Bots & calendar | `GET/POST /api/bots`, `POST /api/bots/check`, `POST /api/bots/{id}/leave`, `GET /api/bots/calendar`, `POST /api/bots/calendar/sync` |
| Tasks & reminders | `GET /api/action-items`, `PATCH /api/action-items/{id}`, `GET /api/action-items/reminders`, `POST /api/action-items/reminders/send` |
| History & dashboard | `GET /api/history`, `GET /api/dashboard/latest` |
| Google | `GET /api/google/status`, `POST /api/google/connect`, `POST /api/google/disconnect`, `GET /api/google/events` |

With `API_AUTH_TOKEN` set, every `/api/*` route needs `Authorization: Bearer <token>`.

## Tests

```powershell
docker compose run --rm --no-deps backend python -m pytest -q             # unit tests
docker compose run --rm -e RUN_DB_TESTS=1 backend python -m pytest -q    # + real PostgreSQL
cd frontend; npx tsc --noEmit; npm run lint; npm run build                # frontend checks
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Page shows *ERR_CONNECTION_REFUSED* / *The Yuqta API is unreachable* | Start Docker Desktop, then `docker compose up -d` |
| Meeting *failed: Nobody spoke while the bot was recording* | Nobody was audible (muted, or alone in the call). Join from two devices and speak |
| Bot never joins | Admit *Yuqta Notetaker* in the call; check the bot status line on the Meetings page |
| *Email is not set up* | Set the Gmail app password (`SMTP_*`) or connect Google and allow sending email |
| *Gmail API has not been used in project … or it is disabled* | The Google Cloud project owner enables the **Gmail API** — or use the app password instead |
| *The email server rejected the login* | `SMTP_PASSWORD` must be a Gmail **app password**, not your normal password |
| Google sign-in *Access blocked* | Add the scopes under Data Access and your address under Audience → Test users |
| Windows: *An Application Control policy has blocked this file* when running Python locally | Use Docker, or reinstall SQLAlchemy without the C extension: `$env:DISABLE_SQLALCHEMY_CEXT=1; pip install --force-reinstall --no-deps --no-binary sqlalchemy "sqlalchemy>=2.0,<3.0"` |

## Privacy

- Participants are told in the chat that the meeting is recorded (`BOT_CONSENT_MESSAGE`); make sure this meets your local rules.
- Recordings are kept by Recall.ai; Yuqta stores transcripts and analysis in its own database.
- Transcripts and customer names are sent to the configured AI provider for analysis.
- Turn on login (`APP_PASSWORD`, `API_AUTH_TOKEN`, `AUTH_SECRET`) before anyone else can reach Yuqta.
