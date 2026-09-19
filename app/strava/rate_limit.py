"""Strava rate-limit budget + 429 backoff, shared across the API and worker
processes via Redis.

WHAT: `call_with_backoff(make_request)` wraps a single HTTP call: it blocks
until the shared budget has room, makes the call, and — on a 429 — sleeps
using Strava's own `Retry-After` header (falling back to a fixed delay if
absent) and retries.

WHY the budget lives in Redis, not in-process memory (see DESIGN.md's
explicit-flags item 4): Strava enforces its limits (200 req/15min,
2,000/day) per API *application*, not per athlete token — every athlete's
backfill, running in whatever worker process picks up that job, draws from
the same budget. An in-process counter would only see its own process's
calls and would under-count true usage the moment two backfills (or the API
process and a worker) call Strava at the same time.

HOW the sliding window is approximated: two Redis integer counters,
`strava:ratelimit:15min` and `strava:ratelimit:day`, each with a TTL equal
to its window. This is a fixed-window counter, not a true sliding log, and
the check-then-increment isn't atomic across processes — under concurrent
load it can go slightly over budget right at a window boundary. That
imprecision is an accepted tradeoff at this project's scale (5-10 users);
Strava's own 429 response is the backstop that makes going slightly over
survivable rather than a hard failure.
"""

import time

import httpx

from worker.queue import redis_conn

_FIFTEEN_MIN_LIMIT = 200
_DAILY_LIMIT = 2000
_FIFTEEN_MIN_KEY = "strava:ratelimit:15min"
_DAILY_KEY = "strava:ratelimit:day"
_MAX_RETRIES = 5
_FALLBACK_BACKOFF_S = 30


def _reserve_budget_slot() -> None:
    while True:
        fifteen_min_count = int(redis_conn.get(_FIFTEEN_MIN_KEY) or 0)
        daily_count = int(redis_conn.get(_DAILY_KEY) or 0)
        if fifteen_min_count < _FIFTEEN_MIN_LIMIT and daily_count < _DAILY_LIMIT:
            pipe = redis_conn.pipeline()
            pipe.incr(_FIFTEEN_MIN_KEY)
            pipe.expire(_FIFTEEN_MIN_KEY, 15 * 60, nx=True)
            pipe.incr(_DAILY_KEY)
            pipe.expire(_DAILY_KEY, 24 * 60 * 60, nx=True)
            pipe.execute()
            return

        wait_s = max(int(redis_conn.ttl(_FIFTEEN_MIN_KEY)), 1)
        time.sleep(min(wait_s, 60))


def call_with_backoff(make_request):
    """`make_request` is a zero-arg callable returning an `httpx.Response`.
    Retries on 429 up to `_MAX_RETRIES` times using Strava's `Retry-After`
    header; the final attempt's response (successful or not) is returned/
    raised as-is so the caller's own `raise_for_status()` still applies.
    """
    response: httpx.Response | None = None
    for _attempt in range(_MAX_RETRIES):
        _reserve_budget_slot()
        response = make_request()
        if response.status_code != 429:
            return response
        retry_after = int(response.headers.get("Retry-After", _FALLBACK_BACKOFF_S))
        time.sleep(retry_after)
    return response
