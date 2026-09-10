"""Tests for GET /health.

WHAT: Verifies the endpoint always returns a well-formed response — it
doesn't assert Postgres/Redis are actually reachable, because this suite
runs in plain `pytest` (no Docker Compose) as well as in CI, where neither
dependency is necessarily up. Confirming real end-to-end health (200 with
both components "ok") is the Phase 0 manual demo step: `docker compose up`,
then `curl localhost:8000/health`.

WHY this split matters: a test that required live infra would make `pytest`
unusable as a fast local/CI check, which defeats the point of having one.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_well_formed_response() -> None:
    response = client.get("/health")

    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("ok", "degraded")
    assert set(body) == {"status", "database", "redis"}


def test_health_status_matches_component_results() -> None:
    response = client.get("/health")
    body = response.json()

    all_ok = body["database"] == "ok" and body["redis"] == "ok"
    assert (body["status"] == "ok") == all_ok
    assert (response.status_code == 200) == all_ok
