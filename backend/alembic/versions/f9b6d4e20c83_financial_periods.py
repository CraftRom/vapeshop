"""Immutable monthly analytics reports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f9b6d4e20c83'
down_revision = 'f8a5c3d10b72'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('financial_periods',
        sa.Column('month', sa.String(7), primary_key=True),
        sa.Column('timezone', sa.String(64), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_by', sa.String(64), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False))

def downgrade():
    op.drop_table('financial_periods')
