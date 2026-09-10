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

    # Required starting Phase 1 (OAuth + token encryption). Optional here so
    # Phase 0 (this scaffold, no auth code yet) can run without them; Phase 1
    # code that actually uses these should validate they're non-empty at the
    # point of use rather than relaxing this back to a hard requirement here.
    fernet_key: str | None = None
    strava_client_id: str | None = None
    strava_client_secret: str | None = None
    strava_redirect_uri: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
