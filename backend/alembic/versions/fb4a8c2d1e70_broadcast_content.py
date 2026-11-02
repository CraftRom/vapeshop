"""Plain text broadcasts and durable create idempotency; preserve old HTML drafts."""
from alembic import op
import sqlalchemy as sa

revision = 'fb4a8c2d1e70'
down_revision = 'fa3d7b2e1c90'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('broadcasts', sa.Column('text_format', sa.String(8), nullable=False, server_default='html'))
    op.add_column('broadcasts', sa.Column('client_key', sa.String(64), nullable=True))
    op.create_index('uq_broadcasts_client_key', 'broadcasts', ['client_key'], unique=True)


def downgrade():
    op.drop_index('uq_broadcasts_client_key', table_name='broadcasts')
    op.drop_column('broadcasts', 'client_key')
    op.drop_column('broadcasts', 'text_format')
