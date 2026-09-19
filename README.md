# raceline

An eval-driven race predictor for triathletes. Connects to Strava, forecasts
finish times from training load, and scores itself against existing
predictors using real results.

Full design rationale (schema, module layout, phased build order, and known
Strava API limitations) lives in [`DESIGN.md`](./DESIGN.md).

## Status

**Phase 3 — Riegel baseline.** Building on Phase 2's ingestion:
`ml/interface.py` defines the swappable `Predictor` abstraction every
prediction method (Riegel now; a trained model and Strava's stub later)
implements, `ml/registry.py` maps a method name to a concrete class, and
`ml/riegel.py` implements Peter Riegel's endurance-extrapolation formula as
the zero-training-data baseline — with an explicit docstring on why applying
a running-derived formula to triathlon totals is an approximation.
`python -m ml.predict_riegel` walks every connected athlete's classified
races with a known finish time and writes one `riegel` `predictions` row per
race that has a usable reference performance (the athlete's prior race).
The trained model, the evaluation report, and the dashboard UI don't exist
yet. This section will be rewritten as each later phase (trained model →
evaluation report → dashboard, per `DESIGN.md`) lands.

Earlier phases: Phase 1 (Strava OAuth2 login, encrypted tokens) and Phase 2
(activity backfill, race classification, lazy detail fetch, training-load
features) are both done — see `DESIGN.md`'s build order for what each
covers, or `git log` for when they landed.

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
- **Modeling** (`ml/`): a swappable `Predictor` interface
  (`ml/interface.py`, `ml/registry.py`) so `predictions.method` values are
  never hardcoded into training/evaluation code — see DESIGN.md's
  "swappable-model mechanism." `ml/riegel.py` is the first concrete
  predictor; a trained gradient-boosting model joins it in Phase 4.
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

### Running the Riegel baseline

Once at least two of an athlete's races have both been through their lazy
detail fetch (i.e. have a known `finish_time_s`), populate `riegel`
predictions for every race that has a usable prior-race reference:

```bash
docker compose exec api python -m ml.predict_riegel
```

This prints how many prediction rows it wrote and is safe to rerun anytime
(it upserts, not duplicates) — rerun it after any new race gets a detail
fetch or a reclassification. A race with no earlier race to extrapolate
from (an athlete's first tracked race) is skipped, not written with a null
prediction — see `ml/predict_riegel.py`'s docstring for why.

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
