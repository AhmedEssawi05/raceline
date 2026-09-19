"""Shared JSON column type: plain JSON everywhere, JSONB specifically on
Postgres.

WHAT: `JSONVariant` is a single `sqlalchemy.JSON` type configured with a
Postgres variant of `JSONB`, for every JSON-shaped column added from Phase 2
onward (`activities.raw_payload`, `race_details.splits`/`elevation_profile`/
`weather`, `training_load_features.extra_features`).

WHY a shared variant instead of importing
`sqlalchemy.dialects.postgresql.JSONB` directly in each model: models need
to keep working against SQLite in tests without a live Postgres (see
app/models/user.py's note on dialect-agnostic types). `JSON().with_variant(
JSONB(), "postgresql")` gets Postgres's indexable, binary JSONB in
production while transparently falling back to plain JSON (stored as TEXT)
against SQLite — one definition instead of repeating this variant wiring in
every model that needs a JSON column.
"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

JSONVariant = JSON().with_variant(JSONB(), "postgresql")
