"""Application configuration.

WHAT: A single `Settings` object, populated from environment variables (or a
`.env` file in local dev), that every other module imports instead of
reading `os.environ` directly.

WHY: Centralizing config in one pydantic-settings model gives us validation
(missing/malformed required vars fail fast at startup, not mid-request) and
one place to see the app's entire environment-variable contract — useful for
both onboarding and for an interviewer skimming the codebase. It mirrors
`.env.example`, which documents *why* each variable exists.

HOW: `get_settings()` is cached with `lru_cache` so the environment is only
parsed once per process; import and call it, don't instantiate `Settings()`
directly elsewhere. FastAPI routes that need config should take it as a
dependency (`Depends(get_settings)`) so it stays mockable in tests, rather
than importing a module-level singleton.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required from Phase 0 onward — the app can't start without a DB/queue.
    database_url: str
    redis_url: str

    # Required starting Phase 1 (OAuth + token encryption + sessions).
    # Optional here, not on the BaseSettings field, so importing this module
    # never fails by itself; each consumer validates non-emptiness at the
    # point of use (app/security.py, app/strava/oauth.py, app/main.py) with
    # an error message that says which var is missing and why, rather than a
    # generic pydantic validation error at import time.
    fernet_key: str | None = None
    strava_client_id: str | None = None
    strava_client_secret: str | None = None
    strava_redirect_uri: str | None = None
    # Signs the session cookie (see app/main.py's SessionMiddleware). Unlike
    # the Strava vars, the app cannot serve *any* request without this —
    # validated once at app-creation time in app/main.py, not lazily.
    session_secret_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
