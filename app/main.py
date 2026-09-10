"""FastAPI application entrypoint.

WHAT: The `create_app()` factory builds and returns the FastAPI app; `app`
is the module-level instance uvicorn serves (`uvicorn app.main:app`). Phase 0
wires up exactly one route, `/health`.

WHY a factory instead of a bare module-level `FastAPI()`: keeps app
construction testable and side-effect-free at import time (tests can call
`create_app()` fresh rather than importing shared global state), and gives
later phases one obvious place to mount routers (`app/routers/*.py`) as they
arrive, instead of scattering `app.include_router(...)` calls wherever.

WHY `/health` actually pings Postgres and Redis instead of just returning
`{"status": "ok"}` unconditionally: this phase's whole purpose is proving
`docker compose up` brings up a correctly wired stack (api, worker, postgres,
redis) — a health check that can't fail doesn't prove that. It returns
component-level detail so a broken dependency is visible without reading
container logs, and HTTP 503 (not 200) when any dependency is unreachable,
so this endpoint is also usable as a real orchestrator health check later.

HOW: `GET /health` → 200 with `{"status": "ok", ...}` when both dependencies
respond, or 503 with per-component error detail otherwise.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import engine
from worker.queue import redis_conn


def create_app() -> FastAPI:
    app = FastAPI(title="raceline")

    @app.get("/health")
    def health() -> JSONResponse:
        components: dict[str, str] = {}

        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            components["database"] = "ok"
        except Exception as exc:  # noqa: BLE001 - report any failure, not just known ones
            components["database"] = f"error: {exc}"

        try:
            redis_conn.ping()
            components["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            components["redis"] = f"error: {exc}"

        healthy = all(v == "ok" for v in components.values())
        status_code = 200 if healthy else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": "ok" if healthy else "degraded", **components},
        )

    return app


app = create_app()
