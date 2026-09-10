"""RQ worker process entrypoint.

WHAT: Starts an RQ `Worker` that blocks, listening for jobs on the shared
"default" queue defined in `worker/queue.py`.

WHY: This is a separate process/container (the `worker` service in
docker-compose) from the FastAPI `api` process — ingestion backfills must be
queued, not run synchronously on login (per spec), so something has to
consume that queue outside the request/response cycle. No job functions
exist yet (Phase 0); this just proves the worker process boots and can talk
to Redis, matching this phase's "docker compose up brings up all services"
demo criterion. Phase 2 adds real jobs under `worker/jobs/`.

HOW: Run via `python -m worker.run_worker` (this is docker-compose's
`worker` service `command`). Not imported by anything else.
"""

from rq import Worker

from worker.queue import queue, redis_conn

if __name__ == "__main__":
    worker = Worker([queue], connection=redis_conn)
    worker.work()
