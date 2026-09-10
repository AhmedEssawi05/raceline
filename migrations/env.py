"""Alembic environment script.

WHAT: Wires Alembic's migration runner to (a) this app's `DATABASE_URL`
(via app.config, not a hardcoded URL in alembic.ini) and (b) `app.db.Base`,
so `alembic revision --autogenerate` can diff the ORM models against the
live schema.

WHY read the URL from app.config instead of alembic.ini's `sqlalchemy.url`:
one source of truth for the DB connection string across the app, worker, and
migrations, so local/CI/deployed environments never need alembic.ini edited
per environment — only the env var changes.

WHY `target_metadata = Base.metadata`: this is boilerplate Alembic needs
regardless. `import app.models` right below is what actually makes it
useful — SQLAlchemy only registers a model on `Base.metadata` once its
module has been imported, so without that line `--autogenerate` would
silently see an empty schema and generate no-op migrations no matter how
many models exist under `app/models/`.

HOW: `alembic revision --autogenerate -m "message"` to generate a migration,
`alembic upgrade head` to apply. Both read DATABASE_URL from the environment
(export it, or run inside the `api`/`worker` containers where it's already set).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 - registers every model on Base.metadata
from app.config import get_settings
from app.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
