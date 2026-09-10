"""Import every ORM model so they register on `app.db.Base.metadata`.

WHY this file matters even though nothing here calls `User`/`OAuthToken`
directly: SQLAlchemy only knows about a model once its module has been
imported at least once. `migrations/env.py` imports this package (not the
individual model modules) specifically so `alembic revision --autogenerate`
sees every table when diffing against the live database. Add new model
modules to this list as they're created in later phases.
"""

from app.models.oauth_token import OAuthToken
from app.models.user import User

__all__ = ["OAuthToken", "User"]
