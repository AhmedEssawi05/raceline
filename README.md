# raceline

An eval-driven race predictor for triathletes. Connects to Strava, forecasts
finish times from training load, and scores itself against existing
predictors using real results.

Full design rationale (schema, module layout, phased build order, and known
Strava API limitations) lives in [`DESIGN.md`](./DESIGN.md).

## Status

**Phase 2 — ingestion.** Building on Phase 1's auth: `POST /races/backfill`
enqueues a full activity backfill for the logged-in user (paginated
`GET /athlete/activities`, shared-budget rate limiting, per-activity error
isolation so one malformed payload never aborts the rest); every ingested
activity is classified by a title-pattern heuristic
(`ingestion/classifier.py`); a confirmed race gets a lazy detail fetch
(`worker/jobs/fetch_race_detail.py`) and rolling-training-load features
(`worker/jobs/compute_features.py`, with explicit null handling for missing
HR/power/history — see `ingestion/feature_engineering.py`).
`GET /races/backfill/status` polls progress, `GET /races` lists
effectively-classified races, and `POST /races/{id}/override` implements
the manual-override toggle. The model, the evaluation report, and the
dashboard UI don't exist yet. This section will be rewritten as each later
phase (Riegel baseline → trained model → evaluation report → dashboard,
per `DESIGN.md`) lands.

## Tech stack

- **API**: FastAPI (`app/`)
- **Auth**: Strava OAuth2, `activity:read_all` only (`app/strava/oauth.py`,
  `app/routers/auth.py`) — tokens encrypted at rest with Fernet
  (`app/security.py`); login session is a signed cookie (Starlette
  `SessionMiddleware`), since Strava OAuth is the only login method
- **Background jobs**: Redis + RQ (`worker/`) — ingestion backfills run here,
  not synchronously on login. `worker/jobs/backfill.py` does the bulk fetch
  + classification; a confirmed race chains into
  `worker/jobs/fetch_race_detail.py` then `worker/jobs/compute_features.py`.
  Progress is tracked in the DB-visible `backfill_jobs` table, not just in
  Redis — see `app/models/backfill_job.py`.
- **Ingestion domain logic** (`ingestion/`): pure, DB/network-free functions
  — `classifier.py` (race-classification heuristic), `activity_parser.py`
  (raw Strava JSON -> row fields, with explicit malformed-payload handling),
  `feature_engineering.py` (rolling training-load windows). Kept ORM-free
  specifically so this logic is unit-testable without a database.
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
  session; keeps the user row and their ingested history for a possible
  reconnect.
- `POST /auth/delete` — hard-deletes the user row and everything that FKs to
  it. This is the "delete my stored data" action from the spec.

### Trying the ingestion flow

Once logged in (above), start a backfill:

```bash
curl -X POST -b cookies.txt http://localhost:8000/races/backfill
```

(`-b cookies.txt` reuses the session cookie from a browser-based login — the
easiest way to do this locally is to hit these endpoints from the browser's
JS console, or via a REST client that shares cookies with your login tab.)

This immediately returns `{"status": "queued", ...}` and hands the actual
work to the `worker` container. Poll progress with:

```bash
curl -b cookies.txt http://localhost:8000/races/backfill/status
```

which reports `pages_fetched`, `activities_ingested`, `activities_failed`,
and `last_error` as the RQ job runs — see `app/models/backfill_job.py` for
why this is a DB row, not something you need to inspect Redis for. Once it
reaches `"status": "succeeded"`:

```bash
curl -b cookies.txt http://localhost:8000/races
```

lists every activity the heuristic (or a manual override) currently
classifies as a race. To correct a misclassification:

```bash
curl -X POST -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"is_race": true}' \
  http://localhost:8000/races/<activity_id>/override
```

`{"is_race": null}` clears a previous override and reverts to the
heuristic's own verdict.

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
