"""add eval_runs, athlete_splits, and eval_metrics tables (Phase 5
evaluation framework)

Revision ID: 9b1e4a7d2f58
Revises: f3a7c1d92e6b
Create Date: 2026-09-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b1e4a7d2f58'
down_revision: Union[str, None] = 'f3a7c1d92e6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('eval_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('model_version_id', sa.Uuid(), nullable=False),
    sa.Column('split_seed', sa.Integer(), nullable=False),
    sa.Column('n_races_total', sa.Integer(), nullable=False),
    sa.Column('n_athletes_test', sa.Integer(), nullable=False),
    sa.Column('notes', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id']),
    sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('athlete_splits',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('eval_run_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('split', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['eval_run_id'], ['eval_runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('eval_run_id', 'user_id', name='uq_athlete_splits_run_user'),
    )

    op.create_table('eval_metrics',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('eval_run_id', sa.Uuid(), nullable=False),
    sa.Column('method', sa.String(), nullable=False),
    sa.Column('distance_category', sa.String(), nullable=True),
    sa.Column('n_races', sa.Integer(), nullable=False),
    sa.Column('mae_minutes', sa.Float(), nullable=True),
    sa.Column('rmse_minutes', sa.Float(), nullable=True),
    sa.Column('mae_pct', sa.Float(), nullable=True),
    sa.Column('rmse_pct', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['eval_run_id'], ['eval_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('eval_metrics')
    op.drop_table('athlete_splits')
    op.drop_table('eval_runs')
