"""Redis connection and RQ queue shared by the API (enqueue side) and the
worker process (consume side).

WHAT: One `Redis` connection and one `Queue` named "default", built from
`REDIS_URL`.

WHY: RQ was chosen over Celery/APScheduler for the backfill job queue (see
DESIGN.md) as the lighter-weight option that still gives real queue
semantics — a single default queue is enough at this project's scale (5-10
users); if job types later need different priorities/isolation, splitting
into multiple named queues is a one-line change here, not a redesign.

HOW: Code that enqueues a job (Phase 2's ingestion endpoints) does
`from worker.queue import queue; queue.enqueue(some_job_function, args...)`.
The worker process (`run_worker.py`) listens on this same queue name.
"""

from redis import Redis
from rq import Queue

from app.config import get_settings

redis_conn = Redis.from_url(get_settings().redis_url)
queue = Queue("default", connection=redis_conn)
