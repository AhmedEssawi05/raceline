# raceline — Phase 1 Design Document

This document is the design reference for raceline's Phase 1 MVP: a triathlon
race finish-time predictor that ingests Strava activity history, identifies
races, engineers training-load features, and backtests a trained model
against Riegel's formula and (where available) Strava's own estimate. The
evaluation framework — an honest, by-athlete-generalization comparison of
prediction methods — is the core deliverable of this project; UI polish and
feature breadth are secondary.

Scope, out-of-scope items, and non-functional requirements follow the
Phase 1 product spec. This document covers schema, module layout, build
order, and known API-limitation assumptions.

## Decided implementation details

A few choices were left open by the product spec and decided during design:

- **Job queue**: Redis + RQ. Chosen over Celery (heavier setup, more moving
  parts than needed at this scale) and a Postgres-polling approach (weaker
  retry/backoff semantics) as the best balance of "real queue" behavior and
  low operational overhead for a 5–10 user MVP.
- **Frontend**: server-rendered Jinja2 templates + HTMX. No separate frontend
  build pipeline, no React — optimizes for shipping speed, which is what the
  spec asked for, and is sufficient for the required views (status page,
  race list with a toggle, aggregate scoreboard).
- **ORM / migrations**: SQLAlchemy 2.0 (typed, `Mapped[...]` declarative
  style) + Alembic. This is the standard FastAPI+Postgres pairing.
  Alembic autogenerates migrations from ORM metadata, which matters here
  because the schema will change repeatedly during early development.
  Sync SQLAlchemy (not async) is used — it's simpler at this scale and lets
  the RQ worker share the exact same models as the API without an async/sync
  split.

## Explicit flags — where Strava's real API diverges from spec assumptions

1. **No predicted-finish-time field exists in Strava API v3.** Segments and
   activities expose leaderboards and KOM/QOM data, not a machine-predicted
   finish time. Per the spec's own fallback instruction, this comparison is
   *not* built via scraping. Instead the `strava_estimate` method exists
   structurally (so the comparison table always lists all three methods) but
   always produces `predicted_finish_time_s = NULL` with an explanatory note.
   `eval_metrics` rows for this method will show `n_races = 0` and null
   metrics — rendered as an explicit "unavailable" row in the report, not a
   crash or a fabricated zero.
2. Segment-leaderboard data is deliberately **not** used as a substitute
   proxy for "Strava's predicted finish time" — doing so would misrepresent
   the comparison and undercut the project's transparency thesis (the whole
   point is that accuracy claims are falsifiable and honestly labeled).
3. **Weather data is a stub**, as the spec itself anticipates —
   `race_details.weather` is a JSONB column, always null in Phase 1, with a
   code TODO for a future weather API keyed on (date, location).
4. **Strava's rate limits (200 req/15min, 2,000/day) are treated as
   app-wide**, not guaranteed independently per athlete token. The
   backoff/retry logic in `strava/rate_limit.py` tracks a shared budget
   across all connected users' backfills — relevant even at 5–10 users if
   several do a first-time backfill around the same time.

## Database schema (PostgreSQL)

### Design decisions

- **Activities and races share one table.** A race *is* an activity Strava
  recorded, with identical raw fields (distance, time, elevation, HR, power).
  Splitting into two tables would duplicate columns or force joins for the
  common "show all activities including races" case. Instead: `activities`
  holds every synced activity; `race_classifications` (1:1, created only when
  relevant) holds classification provenance; `race_details` (1:1, only for
  confirmed races) holds expensive detail-fetch data. This keeps bulk
  ingestion cheap and keeps race-only concerns out of the hot path.
- **Heuristic vs. manual classification are two distinguishable columns**,
  not one collapsed boolean — `heuristic_is_race` (set by the pattern
  matcher, never touched by users) and `manual_override` (nullable; null =
  no override). Effective classification is
  `COALESCE(manual_override, heuristic_is_race)`, exposed as a Postgres
  generated column (`is_race_effective`) for indexable queries. This
  preserves both signals distinguishably, per spec, rather than losing
  provenance in a single flag.
- **Training-load features are a wide, explicit-column table**
  (`training_load_features`), not EAV or a single JSON blob. The feature set
  is small and fixed, so a wide table: (a) is queryable/indexable for eval
  and debugging, (b) maps directly to a pandas/sklearn feature matrix via
  `pd.read_sql`, (c) documents the model's input contract in the schema
  itself — important for a project whose whole point is being legible to a
  reviewer. One `extra_features` JSONB escape hatch exists for experimental
  columns added between migrations.
- **Predictions are row-per-method**, not wide columns
  (`riegel_prediction`, `strava_prediction`, ...). A long/tidy table is what
  both pandas and the eval SQL want for "join predictions across methods for
  this test set," and adding a 4th baseline later costs zero migration —
  just a new `method` value.
- **Train/test split is persisted**, not recomputed implicitly per report
  run. `athlete_splits` records each athlete's assignment for a given
  `eval_run`, produced by a pure `assign_splits(user_ids, seed)` function
  that is unit tested in isolation. This is what makes the split "obviously
  correct and auditable" rather than an unverifiable in-memory shuffle.
- **RQ job progress has DB visibility** via `backfill_jobs`. Redis/RQ holds
  transient job state, but isn't the source of truth for user-facing
  progress across restarts and isn't easily queryable from Jinja templates.
  One row per backfill run, updated at checkpoints; the RQ job ID is stored
  for optional live cross-reference.
- **Deletion**: every user-scoped table has `user_id` FK'd to `users.id`
  with `ON DELETE CASCADE`. "Disconnect and delete my data" is a hard delete
  of the `users` row — the spec says "delete all their stored data," which
  means actual removal, not a hidden soft-delete flag. `is_deleted` on
  `users` exists only transiently to support an "are you sure" confirmation
  step before the cascade fires.
- **Data isolation** is enforced structurally: a `get_current_user`
  dependency injects `user_id` into repository-layer functions rather than
  accepting it as a spoofable route parameter, so per-user queries can't
  accidentally cross accounts. Only aggregate tables (`eval_metrics`) are
  read by the shared scoreboard view.

### Tables

**`users`**

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| strava_athlete_id | BIGINT UNIQUE | no | Strava's numeric athlete id |
| firstname, lastname | TEXT | yes | display only |
| created_at | TIMESTAMPTZ | no | |
| disconnected_at | TIMESTAMPTZ | yes | null = active account |
| is_deleted | BOOLEAN default false | no | transient soft-delete flag ahead of hard-delete cascade |

**`oauth_tokens`** (1:1 with `users`; split out so encrypted secrets aren't
selected alongside profile data by default)

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| user_id | UUID FK→users, UNIQUE | no | |
| access_token_encrypted | BYTEA | no | Fernet-encrypted |
| refresh_token_encrypted | BYTEA | no | Fernet-encrypted |
| expires_at | TIMESTAMPTZ | no | drives pre-expiry refresh |
| scope | TEXT | no | recorded for audit (`activity:read_all`) |
| updated_at | TIMESTAMPTZ | no | |

**`activities`** (every synced activity, race or not)

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| user_id | UUID FK→users | no | indexed |
| strava_activity_id | BIGINT | no | unique per `(user_id, strava_activity_id)` |
| name | TEXT | no | used by the classification heuristic |
| sport_type | TEXT | no | run/ride/swim/triathlon/etc, as reported |
| distance_m | DOUBLE PRECISION | no | |
| moving_time_s | INTEGER | no | |
| elapsed_time_s | INTEGER | no | |
| start_date | TIMESTAMPTZ | no | indexed — drives rolling-window feature queries |
| total_elevation_gain_m | DOUBLE PRECISION | yes | omitted by Strava for some indoor/manual entries |
| avg_heart_rate | DOUBLE PRECISION | yes | **nullable — many users lack HR straps** |
| avg_power_w | DOUBLE PRECISION | yes | **nullable — power meters rare outside cycling; explicit null, not 0** |
| raw_payload | JSONB | no | full Strava response, for reprocessing without re-fetching |
| ingested_at | TIMESTAMPTZ | no | |
| ingestion_error | TEXT | yes | non-null if this row came from a partially malformed payload |

**`race_classifications`** (1:1 with a subset of activities)

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| activity_id | UUID FK→activities, UNIQUE | no | |
| heuristic_is_race | BOOLEAN | no | always set by the pattern matcher |
| heuristic_matched_pattern | TEXT | yes | e.g. `"70.3"` — for debuggability/tests |
| manual_override | BOOLEAN | yes | null = no override |
| distance_category | TEXT (sprint/olympic/70.3/full/other) | yes | derived from `distance_m` |
| updated_at | TIMESTAMPTZ | no | |
| is_race_effective | BOOLEAN, generated `COALESCE(manual_override, heuristic_is_race)` | — | indexable effective classification |

**`race_details`** (1:1, only populated when `is_race_effective = true`)

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| activity_id | UUID FK→activities, UNIQUE | no | |
| splits | JSONB | yes | variable structure by distance/sport — JSONB, not wide columns |
| elevation_profile | JSONB | yes | stream data if available |
| weather | JSONB | yes | **stub — always null in Phase 1** (see Explicit Flags) |
| finish_time_s | INTEGER | yes | authoritative prediction target; null if detail fetch failed |
| fetched_at | TIMESTAMPTZ | no | |
| fetch_error | TEXT | yes | non-null on failed detail fetch (rate-limited, 404, etc.) — allows retry |

**`training_load_features`** (one row per race)

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| activity_id | UUID FK→activities (the race), UNIQUE | no | |
| rolling_weekly_mileage_m | DOUBLE PRECISION | yes | null if insufficient trailing history |
| rolling_weekly_duration_s | DOUBLE PRECISION | yes | |
| long_run_distance_4wk_m | DOUBLE PRECISION | yes | |
| days_since_last_hard_effort | INTEGER | yes | null if no qualifying effort in lookback window |
| taper_indicator | BOOLEAN | yes | null when not computable |
| avg_hr_available | BOOLEAN | no | missing-indicator feature |
| avg_power_available | BOOLEAN | no | missing-indicator feature |
| feature_window_days | INTEGER | no | actual lookback used, for reproducibility |
| extra_features | JSONB | yes | escape hatch for experimental features |
| computed_at | TIMESTAMPTZ | no | |

**`predictions`** (one row per race per method)

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| activity_id | UUID FK→activities (the race) | no | indexed |
| method | TEXT (`riegel` / `strava_estimate` / `trained_model`) | no | |
| predicted_finish_time_s | DOUBLE PRECISION | yes | **null for `strava_estimate` rows — represents "unavailable" cleanly** |
| model_version_id | UUID FK→model_versions | yes | non-null only for `trained_model` rows |
| predicted_at | TIMESTAMPTZ | no | |
| notes | TEXT | yes | e.g. "unavailable: Strava API does not expose predicted finish time" |

Unique constraint on `(activity_id, method, model_version_id)`; reruns upsert.

**`model_versions`**

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| algorithm | TEXT | no | e.g. `gradient_boosting`, `linear_regression` — matches `ml/registry.py` key |
| trained_at | TIMESTAMPTZ | no | |
| hyperparameters | JSONB | yes | |
| training_athlete_ids | JSONB (array) | no | audit trail for the athlete split used |
| artifact_path | TEXT | no | e.g. `./model_artifacts/<id>.joblib` |
| feature_schema_version | TEXT | no | guards against loading against a changed feature table |

**`athlete_splits`**

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| eval_run_id | UUID FK→eval_runs | no | |
| user_id | UUID FK→users | no | |
| split | TEXT (`train` / `test`) | no | |

Unique on `(eval_run_id, user_id)`.

**`eval_runs`**

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| run_at | TIMESTAMPTZ | no | |
| model_version_id | UUID FK→model_versions | no | |
| split_seed | INTEGER | no | reproducibility |
| n_races_total | INTEGER | no | denormalized for small-N caveat display |
| n_athletes_test | INTEGER | no | |
| notes | TEXT | yes | |

**`eval_metrics`**

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| eval_run_id | UUID FK→eval_runs | no | |
| method | TEXT | no | |
| distance_category | TEXT | yes | null row = all categories combined |
| n_races | INTEGER | no | sample size backing this row — required for inline small-N flagging |
| mae_minutes | DOUBLE PRECISION | yes | null if `n_races = 0` |
| rmse_minutes | DOUBLE PRECISION | yes | |
| mae_pct | DOUBLE PRECISION | yes | |
| rmse_pct | DOUBLE PRECISION | yes | |

This table backs both the aggregate scoreboard dashboard view and the eval
report — the dashboard reads the latest `eval_run`'s rows rather than
computing anything live, which is what keeps it aggregate-only.

**`backfill_jobs`**

| column | type | nullable | notes |
|---|---|---|---|
| id | UUID PK | no | |
| user_id | UUID FK→users | no | |
| rq_job_id | TEXT | yes | correlate to Redis/RQ for live debugging |
| status | TEXT (`queued`/`running`/`succeeded`/`failed`) | no | |
| pages_fetched | INTEGER default 0 | no | |
| activities_ingested | INTEGER default 0 | no | |
| activities_failed | INTEGER default 0 | no | malformed activities skipped without crashing the job |
| started_at | TIMESTAMPTZ | yes | |
| finished_at | TIMESTAMPTZ | yes | |
| last_error | TEXT | yes | |

## Module / directory structure

```
raceline/
├── pyproject.toml                 # deps, tool config (ruff/black/mypy/pytest)
├── docker-compose.yml             # api, worker, postgres, redis services
├── Dockerfile                     # shared image for api + worker (different CMD)
├── .env.example                   # STRAVA_CLIENT_ID/SECRET, FERNET_KEY, DATABASE_URL, REDIS_URL
├── alembic.ini
├── README.md                      # setup, how to run eval report, current model performance/limitations
├── DESIGN.md                      # this file
│
├── migrations/                    # Alembic migration scripts
│   ├── env.py
│   └── versions/
│
├── app/                            # FastAPI application (web tier)
│   ├── main.py                     # app factory, router mounting, Jinja2Templates setup
│   ├── config.py                   # pydantic-settings: env-driven config
│   ├── db.py                       # SQLAlchemy engine/session factory, get_db dependency
│   ├── security.py                 # Fernet encrypt/decrypt helpers for tokens
│   ├── deps.py                     # get_current_user and other FastAPI dependencies
│   │
│   ├── models/                     # SQLAlchemy 2.0 declarative models (mirrors schema above)
│   │   ├── user.py
│   │   ├── oauth_token.py
│   │   ├── activity.py
│   │   ├── race.py                 # RaceClassification, RaceDetail
│   │   ├── features.py             # TrainingLoadFeatures
│   │   ├── prediction.py           # Prediction, ModelVersion
│   │   ├── evaluation.py           # AthleteSplit, EvalRun, EvalMetric
│   │   └── backfill_job.py
│   │
│   ├── schemas/                    # Pydantic request/response DTOs, separate from ORM models
│   │   ├── auth.py
│   │   ├── race.py
│   │   └── dashboard.py
│   │
│   ├── routers/                    # FastAPI route modules
│   │   ├── auth.py                 # /auth/strava/login, /auth/strava/callback, /auth/disconnect, /auth/delete
│   │   ├── races.py                # per-user race list, HTMX toggle endpoint for mark/unmark
│   │   └── dashboard.py            # aggregate scoreboard view
│   │
│   ├── strava/                     # Strava API client, isolated from ingestion logic
│   │   ├── client.py               # OAuth token exchange, GET /athlete/activities, GET /activities/{id}
│   │   ├── oauth.py                # authorization-code flow helpers, token refresh logic
│   │   └── rate_limit.py           # backoff/retry policy shared by client + worker jobs
│   │
│   ├── repositories/                # query layer — all DB access, always user_id-scoped
│   │   ├── user_repo.py
│   │   ├── activity_repo.py
│   │   ├── race_repo.py
│   │   └── eval_repo.py            # aggregate-only reads for the dashboard scoreboard
│   │
│   └── templates/                   # Jinja2 templates + HTMX fragments
│       ├── base.html
│       ├── login.html
│       ├── account_status.html
│       ├── races_list.html          # includes HTMX partial for mark/unmark toggle
│       ├── _race_row.html           # HTMX swap target fragment
│       └── scoreboard.html
│
├── worker/                          # RQ worker process + job definitions
│   ├── run_worker.py                 # entrypoint: rq.Worker listening on queues
│   ├── queue.py                      # RQ Queue/Redis connection setup, enqueue helpers
│   └── jobs/
│       ├── backfill.py               # paginated activity fetch, writes backfill_jobs progress
│       ├── classify_race.py          # runs heuristic classifier on newly ingested activities
│       ├── fetch_race_detail.py      # lazy detail/laps fetch for confirmed races only
│       └── compute_features.py       # training-load feature engineering for a given race
│
├── ingestion/                        # pure ingestion/domain logic, importable by app and worker
│   ├── classifier.py                  # title pattern-matching heuristic (pure function, unit tested)
│   ├── activity_parser.py             # raw Strava JSON -> Activity row, isolates malformed-payload handling
│   └── feature_engineering.py         # rolling window / taper / hard-effort computations, explicit null handling
│
├── ml/                                # modeling — swappable-predictor design lives here
│   ├── interface.py                   # abstract Predictor base class: fit(X, y) / predict(X) / method_name
│   ├── registry.py                    # PREDICTOR_REGISTRY: dict[str, Type[Predictor]]
│   ├── riegel.py                      # RiegelPredictor — zero-training-data baseline, explicit limitation docstring
│   ├── gradient_boosting.py           # GradientBoostingPredictor — sklearn GBR wrapper, default "trained_model"
│   ├── linear_baseline.py             # LinearRegressionPredictor — demonstrates swappability
│   ├── strava_estimate.py             # StravaEstimatePredictor — always returns None/unavailable
│   ├── features.py                    # build_feature_matrix(): DB rows -> pandas DataFrame
│   └── train.py                       # CLI: loads train-split athletes, fits a Predictor, persists ModelVersion + artifact
│
├── evaluation/                        # the core deliverable
│   ├── split.py                       # assign_splits(user_ids, seed) -> {user_id: "train"/"test"}
│   ├── metrics.py                     # MAE/RMSE in minutes and % of finish time
│   ├── report.py                      # orchestrates: load test set -> predict -> compute eval_metrics -> persist EvalRun
│   └── run_report.py                  # rerunnable CLI ("python -m evaluation.run_report")
│
├── notebooks/
│   └── eval_report.ipynb              # thin wrapper importing evaluation.report
│
└── tests/
    ├── conftest.py                     # pytest fixtures: test DB, factory helpers
    ├── test_classifier.py              # race-classification heuristic
    ├── test_feature_engineering.py     # training-load feature pipeline incl. null-handling cases
    ├── test_riegel.py                  # Riegel's formula correctness
    ├── test_split.py                   # athlete-split logic — heaviest coverage, highest risk
    ├── test_metrics.py                 # MAE/RMSE and % calculations
    └── test_ingestion_error_handling.py # malformed activity doesn't crash whole-user ingestion
```

**Swappable-model mechanism**: `ml/interface.py` defines an abstract
`Predictor` (`fit`, `predict`, `method_name`). `ml/registry.py` maps a config
string (e.g. `RACELINE_MODEL_ALGORITHM=gradient_boosting`) to a concrete
class. `ml/train.py` and `evaluation/report.py` only ever call
`registry.get_predictor(name)` — never import a concrete class directly — so
swapping gradient boosting for linear regression is a one-line config change
plus registering the class, with zero changes to ingestion, evaluation, or
the dashboard. `RiegelPredictor` and `StravaEstimatePredictor` implement the
same interface (no-op `fit`) purely so the evaluation loop can treat all
three methods uniformly.

## Build order

Each phase ends in something independently demoable, matching the spec's
requested sequence: auth → ingestion → Riegel baseline → trained model →
evaluation report → dashboard.

**Phase 0 — Scaffolding**
`pyproject.toml`, Docker Compose (api/worker/postgres/redis), Alembic init,
FastAPI app with a health check.
*Demo*: `docker compose up` brings up all four services; `/health` returns 200.

**Phase 1 — Auth**
Strava OAuth2 authorization-code flow, `users`/`oauth_tokens` tables, Fernet
token encryption, refresh-before-expiry, disconnect + delete-data endpoints
(cascade delete).
*Demo*: log in with a real Strava account, see connected status, disconnect,
confirm tokens are gone from the DB.

**Phase 2 — Ingestion**
`activities`/`backfill_jobs` tables; RQ backfill job with paginated
`GET /athlete/activities`, rate-limit backoff/retry, per-activity error
isolation; race classification heuristic + `race_classifications` table;
manual override toggle (bare endpoint, ahead of the dashboard, to validate
the schema end-to-end); lazy `race_details` fetch for confirmed races;
`training_load_features` computation with explicit null handling.
*Demo*: connect a real account, watch backfill progress, see races
auto-identified, manually override one, confirm a feature row with correct
nulls for missing HR/power/history.

**Phase 3 — Riegel baseline**
`ml/interface.py`/`registry.py` scaffolding (built now so Phase 4 slots in
cleanly); `ml/riegel.py` with an explicit limitation docstring; `predictions`
table populated for classified races.
*Demo*: run the script, inspect `riegel` rows against real races.

**Phase 4 — Trained model**
`model_versions` table; `ml/gradient_boosting.py`; `ml/features.py`
(DB → feature matrix); `ml/train.py` (accepts an explicit athlete-id list so
Phase 5 can call it train-split-only). `predictions` gets `trained_model`
rows tied to a `model_version_id`.
*Demo*: train on real ingested data, persist an artifact, generate
predictions, spot-check against actual finish times.

**Phase 5 — Evaluation framework (core deliverable)**
`evaluation/split.py` + `athlete_splits`, built and unit-tested first given
its risk profile; wire training to train-split athletes only; predictions
generated only for test-split athletes' races; `evaluation/metrics.py`
(MAE/RMSE, minutes + %); `eval_runs`/`eval_metrics` tables; `report.py` +
`run_report.py` producing the three-method comparison table with
distance-category breakdown and small-N caveats printed inline; a thin
notebook wrapper.
*Demo*: `python -m evaluation.run_report` against real (small) DB state
produces a reproducible comparison table with explicit caveats.

**Phase 6 — Dashboard**
Jinja2 + HTMX: login/status page, per-user race list with predicted-vs-actual
and a live mark/unmark toggle, aggregate scoreboard reading the latest
`eval_run`'s `eval_metrics` (aggregate-only).
*Demo*: full click-through of the app.
