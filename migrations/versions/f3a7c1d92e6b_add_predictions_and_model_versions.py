"""add model_versions and predictions tables (Phase 3 Riegel baseline)

Revision ID: f3a7c1d92e6b
Revises: 8c2f0a19b3d4
Create Date: 2026-09-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f3a7c1d92e6b'
down_revision: Union[str, None] = '8c2f0a19b3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('model_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('algorithm', sa.String(), nullable=False),
    sa.Column('trained_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('hyperparameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('training_athlete_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('artifact_path', sa.String(), nullable=False),
    sa.Column('feature_schema_version', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('predictions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('activity_id', sa.Uuid(), nullable=False),
    sa.Column('method', sa.String(), nullable=False),
    sa.Column('predicted_finish_time_s', sa.Float(), nullable=True),
    sa.Column('model_version_id', sa.Uuid(), nullable=True),
    sa.Column('predicted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('notes', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('activity_id', 'method', 'model_version_id', name='uq_predictions_activity_method_model'),
    )
    op.create_index('ix_predictions_activity_id', 'predictions', ['activity_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_predictions_activity_id', table_name='predictions')
    op.drop_table('predictions')
    op.drop_table('model_versions')
