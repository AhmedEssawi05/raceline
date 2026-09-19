# WHAT: one image shared by both the `api` and `worker` services in
# docker-compose.yml — they run the same codebase against the same
# dependencies, just with a different container `command`.
# WHY one image instead of two Dockerfiles: api and worker import each
# other's packages (worker/queue.py is imported by app/main.py's health
# check; Phase 2's ingestion routes will enqueue into worker/jobs/) — one
# image keeps their dependency set and Python version identical by
# construction, instead of two Dockerfiles drifting apart over time.
FROM python:3.11-slim

WORKDIR /srv/raceline

# System deps for psycopg[binary] and building any transitive C extensions.
# (psycopg[binary] ships prebuilt wheels for linux/amd64+arm64, so this is
# mostly a safety net for other deps' sdists rather than a hard requirement.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# All source is copied before `pip install .` runs, rather than
# pyproject.toml first for layer-caching, because hatchling's build backend
# (see pyproject.toml's `[tool.hatch.build.targets.wheel] packages = [...]`)
# validates that those package directories actually exist on disk at build
# time — copying pyproject.toml alone would fail. Trading away dependency-
# layer caching for a build that can't silently install stale code is the
# right tradeoff at this project's size.
COPY pyproject.toml ./
COPY app ./app
COPY worker ./worker
COPY ingestion ./ingestion
COPY ml ./ml
COPY evaluation ./evaluation
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN pip install --no-cache-dir .

# No CMD here on purpose — docker-compose.yml sets an explicit `command` per
# service (uvicorn for api, `python -m worker.run_worker` for worker) so this
# one image's two roles are visible in docker-compose.yml, not hidden here.
