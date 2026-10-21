"""Idempotent Mini App support messages."""
from alembic import op
import sqlalchemy as sa
revision = 'f8a5c3d10b72'
down_revision = 'f7d4b2c90a61'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('support_messages', sa.Column('client_request_id', sa.String(64), nullable=True))
    op.create_index('uq_support_messages_client_request', 'support_messages', ['thread_id', 'client_request_id'], unique=True)

def downgrade():
    op.drop_index('uq_support_messages_client_request', table_name='support_messages')
    op.drop_column('support_messages', 'client_request_id')
