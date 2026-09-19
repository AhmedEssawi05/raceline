"""add activities, race_classifications, race_details,
training_load_features, and backfill_jobs tables (Phase 2 ingestion)

Revision ID: 8c2f0a19b3d4
Revises: 5f056e8e0030
Create Date: 2026-09-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8c2f0a19b3d4'
down_revision: Union[str, None] = '5f056e8e0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('activities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('strava_activity_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('sport_type', sa.String(), nullable=False),
    sa.Column('distance_m', sa.Float(), nullable=False),
    sa.Column('moving_time_s', sa.Integer(), nullable=False),
    sa.Column('elapsed_time_s', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('total_elevation_gain_m', sa.Float(), nullable=True),
    sa.Column('avg_heart_rate', sa.Float(), nullable=True),
    sa.Column('avg_power_w', sa.Float(), nullable=True),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ingestion_error', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'strava_activity_id', name='uq_activities_user_strava_id'),
    )
    op.create_index('ix_activities_user_id_start_date', 'activities', ['user_id', 'start_date'], unique=False)

    op.create_table('race_classifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('activity_id', sa.Uuid(), nullable=False),
    sa.Column('heuristic_is_race', sa.Boolean(), nullable=False),
    sa.Column('heuristic_matched_pattern', sa.String(), nullable=True),
    sa.Column('manual_override', sa.Boolean(), nullable=True),
    sa.Column('distance_category', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column(
        'is_race_effective',
        sa.Boolean(),
        sa.Computed('COALESCE(manual_override, heuristic_is_race)', persisted=True),
        nullable=False,
    ),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('activity_id'),
    )
    op.create_index('ix_race_classifications_is_race_effective', 'race_classifications', ['is_race_effective'], unique=False)

    op.create_table('race_details',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('activity_id', sa.Uuid(), nullable=False),
    sa.Column('splits', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('elevation_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('weather', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('finish_time_s', sa.Integer(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('fetch_error', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('activity_id'),
    )

    op.create_table('training_load_features',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('activity_id', sa.Uuid(), nullable=False),
    sa.Column('rolling_weekly_mileage_m', sa.Float(), nullable=True),
    sa.Column('rolling_weekly_duration_s', sa.Float(), nullable=True),
    sa.Column('long_run_distance_4wk_m', sa.Float(), nullable=True),
    sa.Column('days_since_last_hard_effort', sa.Integer(), nullable=True),
    sa.Column('taper_indicator', sa.Boolean(), nullable=True),
    sa.Column('avg_hr_available', sa.Boolean(), nullable=False),
    sa.Column('avg_power_available', sa.Boolean(), nullable=False),
    sa.Column('feature_window_days', sa.Integer(), nullable=False),
    sa.Column('extra_features', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('activity_id'),
    )

    op.create_table('backfill_jobs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('rq_job_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('pages_fetched', sa.Integer(), nullable=False),
    sa.Column('activities_ingested', sa.Integer(), nullable=False),
    sa.Column('activities_failed', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('backfill_jobs')
    op.drop_table('training_load_features')
    op.drop_table('race_details')
    op.drop_index('ix_race_classifications_is_race_effective', table_name='race_classifications')
    op.drop_table('race_classifications')
    op.drop_index('ix_activities_user_id_start_date', table_name='activities')
    op.drop_table('activities')
