# raceline

An eval-driven race predictor for triathletes. Connects to Strava, forecasts
finish times from training load, and scores itself against existing
predictors using real results.

Full design rationale (schema, module layout, phased build order, and known
Strava API limitations) lives in [`DESIGN.md`](./DESIGN.md).

## Status

**Phase 1 — auth.** Strava OAuth2 login works end-to-end: authorization-
code flow, encrypted-at-rest tokens, refresh-before-expiry, and disconnect
(revoke + keep history) vs. delete (hard-delete everything) as two distinct
actions. Ingestion, the model, the evaluation report, and the dashboard UI
don't exist yet. This section will be rewritten as each later phase
(ingestion → Riegel baseline → trained model → evaluation report →
dashboard, per `DESIGN.md`) lands.

## Tech stack

- **API**: FastAPI (`app/`)
- **Auth**: Strava OAuth2, `activity:read_all` only (`app/strava/oauth.py`,
  `app/routers/auth.py`) — tokens encrypted at rest with Fernet
  (`app/security.py`); login session is a signed cookie (Starlette
  `SessionMiddleware`), since Strava OAuth is the only login method
- **Background jobs**: Redis + RQ (`worker/`) — ingestion backfills run here,
  not synchronously on login
- **Database**: PostgreSQL, via SQLAlchemy 2.0 + Alembic (`app/db.py`,
  `app/models/`, `migrations/`)
- **Modeling** (Phase 3+): scikit-learn, behind a swappable `Predictor`
  interface (`ml/`, not built yet)
- **Frontend** (Phase 6): server-rendered Jinja2 + HTMX (not built yet) — the
  auth endpoints below return bare JSON for now, standing in for the
  dashboard until Phase 6

## Local setup (Docker Compose)

```bash
cp .env.example .env
```

Fill in `.env`:
- `SESSION_SECRET_KEY` and `FERNET_KEY` are **required** — the app refuses
  to start without them. Generate each with the one-liner commented above
  it in `.env.example`.
- `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` are only needed to actually
  log in. Register a Strava API app at
  [strava.com/settings/api](https://www.strava.com/settings/api) — set its
  "Authorization Callback Domain" to `localhost`. Without these, everything
  else still runs; hitting `/auth/strava/login` just raises a clear error.

```bash
docker compose up --build
```

Then check `http://localhost:8000/health`. A healthy stack returns:

```json
{"status": "ok", "database": "ok", "redis": "ok"}
```

If Postgres or Redis isn't reachable yet (e.g. it's still starting), you'll
see `"status": "degraded"` with an `"error: ..."` detail on the failing
component and an HTTP 503 — that's the health check doing its job, not a bug.

Apply the database schema (only needed once per fresh database, or after
pulling a new migration):

```bash
docker compose exec api alembic upgrade head
```

### Trying the login flow

With real Strava credentials in `.env`, open
`http://localhost:8000/auth/strava/login` in a browser (not `curl` — Strava's
consent screen needs a real browser session). After approving, you land on
`GET /auth/status`, e.g.:

```json
{"connected": true, "strava_athlete_id": 12345, "firstname": "Jane", "lastname": "Doe", "connected_since": "2026-09-10T19:00:00Z"}
```

- `POST /auth/disconnect` — revokes the token with Strava and clears the
  session; keeps the user row (and, once Phase 2 exists, their history) for
  a possible reconnect.
- `POST /auth/delete` — hard-deletes the user row and everything that FKs to
  it. This is the "delete my stored data" action from the spec.

## Running tests

Tests run standalone, without Docker Compose or a live Strava app — auth
tests use an in-memory SQLite DB and mock only the two functions that would
otherwise call Strava's servers (`app.strava.oauth.exchange_code_for_token` /
`.deauthorize`); see `tests/conftest.py` for why:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Evaluation report

Not runnable yet — this arrives in Phase 5. Once it exists, this section
will document how to regenerate the model-vs-baselines comparison report
from the current database state, and will state current model performance
and known limitations (small sample size, self-selected user population,
missing swim data) directly, since this README is itself meant to hold up
under an interviewer's read.
