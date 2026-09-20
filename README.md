# raceline

[![CI](https://github.com/AhmedEssawi05/raceline/actions/workflows/ci.yml/badge.svg)](https://github.com/AhmedEssawi05/raceline/actions/workflows/ci.yml)

An eval-driven race predictor for triathletes. Connects to Strava, forecasts
finish times from training load, and scores itself against existing
predictors using real results.

Full design rationale (schema, module layout, phased build order, and known
Strava API limitations) lives in [`DESIGN.md`](./DESIGN.md).

## Status

**All six phases of the Phase 1 MVP are done.** Strava OAuth login →
activity ingestion/classification → Riegel baseline → trained model →
evaluation report → dashboard, per `DESIGN.md`'s build order. The headline
piece — `DESIGN.md` calls it the core deliverable — is Phase 5's evaluation
framework: `python -m evaluation.run_report` assigns a deterministic,
by-*athlete* (not by-race) train/test split, trains a fresh model on
train-split athletes only, generates held-out predictions for test-split
athletes' races from all three methods (`riegel` / `strava_estimate` /
`trained_model`), and prints an honest MAE/RMSE comparison with inline
small-N caveats. Phase 6 puts a server-rendered Jinja2 + HTMX dashboard on
top of the exact same repository functions: a status page, a race list with
predicted-vs-actual and a live unmark toggle, and a public, aggregate-only
scoreboard reading the latest eval run.

See `DESIGN.md`'s build order for what each phase covers in depth, or
`git log` for when they landed. Known, deliberate limitations (small sample
size, self-selected user population, no swim/missing-distance data,
`strava_estimate`'s permanent unavailability, the dashboard's unmark-only
override) are documented inline where each decision was made — see
`DESIGN.md`'s Explicit Flags list and this README's usage sections below.

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
  (`ml/interface.py`, `ml/registry.py`) so no training/evaluation code
  hardcodes a concrete algorithm — see DESIGN.md's "swappable-model
  mechanism." `ml/riegel.py` is the zero-training baseline;
  `ml/gradient_boosting.py` (`HistGradientBoostingRegressor`, chosen for its
  native missing-value support) is the trained-model baseline, fit via
  `ml/train.py` from `ml/features.py`'s feature matrix.
- **Database**: PostgreSQL, via SQLAlchemy 2.0 + Alembic (`app/db.py`,
  `app/models/`, `migrations/`)
- **Evaluation** (`evaluation/`): `split.py` (deterministic, by-athlete
  train/test split — the highest-risk, most heavily-tested module in this
  repo, since a wrong split would silently invalidate every accuracy
  number), `metrics.py` (MAE/RMSE, minutes and % of finish time),
  `report.py` + `run_report.py` (orchestrates training + held-out
  prediction + metrics, persists `eval_runs`/`eval_metrics`).
- **Frontend** (`app/templates/`, `app/routers/dashboard.py`):
  server-rendered Jinja2 + HTMX, no build pipeline — a status page, a race
  list with predicted-vs-actual and a live HTMX unmark toggle, and a public
  aggregate-only scoreboard. The bare-JSON endpoints (`/auth/*`, `/races/*`)
  remain the integration surface for tests/API clients; the dashboard is a
  presentation layer on the same repository functions, not a replacement.

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

### Training the gradient-boosting model

Once at least a few races across your connected accounts have computed
training-load features (`worker/jobs/compute_features.py` has run) and a
known finish time, train the `trained_model` baseline:

```bash
docker compose exec api python -m ml.train
```

This builds the feature matrix, fits the algorithm named by
`RACELINE_MODEL_ALGORITHM` (default `gradient_boosting`), writes the fitted
model to `model_artifacts/<model_version_id>.joblib`, prints the new
`model_versions.id`, and writes `trained_model` predictions for every race
it trained on. Restrict training to specific athletes (the hook Phase 5's
evaluation will use for a real train/test split) with:

```bash
docker compose exec api python -m ml.train --athlete-ids <uuid1>,<uuid2>
```

These predictions are generated on the model's *own* training set — a
sanity check that the pipeline works end-to-end, not a claim about
generalization. That honest, held-out comparison is Phase 5's job.

### Running the evaluation report

Once several athletes each have a few classified races with computed
features and known finish times, run the full comparison:

```bash
docker compose exec api python -m evaluation.run_report
```

This assigns a deterministic athlete train/test split (`--seed`, default
42 — the same seed and athlete population always produce the same split),
trains a fresh model on train-split athletes only, generates `riegel` and
`trained_model` predictions plus explanatory `strava_estimate` rows for
test-split athletes' races, and prints a table like:

```
Eval run <uuid> — seed=42, 2 test athlete(s), 5 test race(s)
method          category       n  MAE(min) RMSE(min)   MAE(%)  RMSE(%)
-------------------------------------------------------------------
riegel          all            4       3.2       4.1      2.8      3.5
strava_estimate all            0       n/a       n/a      n/a      n/a
trained_model   all            5      11.7      14.2      9.9     12.1 (small N)
```

`n` is the sample size backing each row — `(small N)` flags rows under 5
test races, where a single unusual prediction can swing the mean enough
that the number shouldn't be read as "this method's typical accuracy."
`strava_estimate` is always `n=0`/`n/a`: Strava's API exposes no predicted
finish time (see `DESIGN.md`'s Explicit Flags), so this row is the honest
"unavailable" signal, not an omission. The latest run's results are also
visible at `http://localhost:8000/scoreboard` (public, no login — see
below).

### The dashboard

With `docker compose up` running, open `http://localhost:8000/`:

- **`/`** — login page (logged out) or account status page (logged in),
  including a "Start backfill" button and disconnect/delete actions.
- **`/dashboard/races`** — your races with predicted-vs-actual finish times
  and a live "Unmark as race" button (HTMX — no page reload) for correcting
  a false positive. Marking an activity the classifier missed entirely
  isn't supported yet — that would need a full activity browser, out of
  scope for this MVP (see `app/routers/dashboard.py`).
- **`/scoreboard`** — the latest `evaluation.run_report` result, aggregate
  only, no login required.

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

## Known limitations

Stated directly, since this README is meant to hold up under an
interviewer's read, not just a demo:

- **Small, self-selected sample.** This is a 5–10 user project; every
  "small N" caveat in the evaluation report is real, not a formality.
- **`strava_estimate` is permanently unavailable.** Strava's API exposes no
  predicted finish time — this isn't a bug or a TODO, see `DESIGN.md`'s
  Explicit Flags item 1.
- **Riegel's formula is a running formula applied to triathlon totals.**
  It ignores discipline mix, transitions, and pacing strategy — deliberately
  the weakest baseline in the comparison (`ml/riegel.py`).
- **Weather is a stub.** `race_details.weather` is always null in this MVP.
- **The dashboard's race-list toggle is unmark-only.** Correcting a false
  positive works; catching a race the classifier missed entirely does not
  (`app/routers/dashboard.py`).
- **No swim-specific handling.** Distance categories are triathlon-shaped
  (sprint/olympic/70.3/full), but per-discipline splits within a race
  aren't modeled as separate features.
