"""Mark automatic FAQ replies in support history.

revision: 2e7b6a4c9d10
revises: 6b9f1c2d4e70
"""
from alembic import op
import sqlalchemy as sa

revision = "2e7b6a4c9d10"
down_revision = "6b9f1c2d4e70"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "support_messages",
        sa.Column("is_automatic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("support_messages", "is_automatic")
