# raceline

An eval-driven race predictor for triathletes. Connects to Strava, forecasts
finish times from training load, and scores itself against existing
predictors using real results.

Full design rationale (schema, module layout, phased build order, and known
Strava API limitations) lives in [`DESIGN.md`](./DESIGN.md).

## Status

**Phase 0 — scaffolding only.** Nothing product-facing works yet: no OAuth,
no ingestion, no model, no dashboard. What exists right now is the project
skeleton and a `/health` endpoint that proves the four services (api, worker,
postgres, redis) are wired together correctly. This section will be
rewritten as each later phase (auth → ingestion → Riegel baseline → trained
model → evaluation report → dashboard, per `DESIGN.md`) lands.

## Tech stack

- **API**: FastAPI (`app/`)
- **Background jobs**: Redis + RQ (`worker/`) — ingestion backfills run here,
  not synchronously on login
- **Database**: PostgreSQL, via SQLAlchemy 2.0 + Alembic (`app/db.py`,
  `migrations/`)
- **Modeling** (Phase 3+): scikit-learn, behind a swappable `Predictor`
  interface (`ml/`, not built yet)
- **Frontend** (Phase 6): server-rendered Jinja2 + HTMX (not built yet)

## Local setup (Docker Compose)

```bash
cp .env.example .env
# Phase 0 only needs the Postgres/Redis vars in .env.example, which already
# have working defaults. FERNET_KEY and the STRAVA_* vars aren't consumed by
# any code yet — Phase 1 will need them filled in.

docker compose up --build
```

Then check `http://localhost:8000/health`. A healthy stack returns:

```json
{"status": "ok", "database": "ok", "redis": "ok"}
```

If Postgres or Redis isn't reachable yet (e.g. it's still starting), you'll
see `"status": "degraded"` with an `"error: ..."` detail on the failing
component and an HTTP 503 — that's the health check doing its job, not a bug.

## Running tests

Tests run standalone, without Docker Compose — they don't require a live
Postgres/Redis (see `tests/conftest.py` for why: `/health`'s tests assert the
response is well-formed, not that dependencies are actually reachable, so
the suite stays fast in plain CI):

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
