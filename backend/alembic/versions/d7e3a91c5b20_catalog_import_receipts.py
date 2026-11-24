"""Receipts of applied XLSX catalog imports: a repeated request is not re-applied.

Revision ID: d7e3a91c5b20
Revises: fb4a8c2d1e70
"""
from alembic import op
import sqlalchemy as sa

revision = "d7e3a91c5b20"
down_revision = "fb4a8c2d1e70"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("catalog_imports",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("actor", sa.String(64), nullable=False, server_default=""),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_catalog_imports_created_at", "catalog_imports", ["created_at"])


def downgrade():
    op.drop_index("ix_catalog_imports_created_at", table_name="catalog_imports")
    op.drop_table("catalog_imports")
