"""Durable XLSX import jobs with checkpoints and leases (A02).

Revision ID: a3d9b6e14f02
Revises: d7e3a91c5b20
"""
from alembic import op
import sqlalchemy as sa

revision = "a3d9b6e14f02"
down_revision = "d7e3a91c5b20"
branch_labels = None
depends_on = None

COLUMNS = (
    ("mode", sa.String(16), ""), ("prices", sa.String(16), ""), ("payload", sa.Text(), None),
    ("rows_total", sa.Integer(), "0"), ("rows_done", sa.Integer(), "0"), ("attempts", sa.Integer(), "0"),
    ("lease_owner", sa.String(64), ""), ("lease_until", sa.DateTime(timezone=True), None), ("error", sa.Text(), ""),
)


def upgrade():
    for name, kind, default in COLUMNS:
        op.add_column("catalog_imports", sa.Column(
            name, kind, nullable=default is None, **({"server_default": default} if default is not None else {})))
    # Receipts written by v1.16-v1.19 were applied synchronously: mark them done.
    op.execute("UPDATE catalog_imports SET status = 'done' WHERE status = 'running' AND result <> ''")
    op.execute("DELETE FROM catalog_imports WHERE status = 'running'")
    # Batch mode: SQLite (QA) cannot ALTER COLUMN in place; PostgreSQL runs it directly.
    with op.batch_alter_table("catalog_imports") as batch:
        batch.alter_column("status", existing_type=sa.String(16), server_default="queued")
    op.create_index("ix_catalog_imports_status", "catalog_imports", ["status", "created_at"])


def downgrade():
    op.drop_index("ix_catalog_imports_status", table_name="catalog_imports")
    op.execute("DELETE FROM catalog_imports WHERE status <> 'done'")
    with op.batch_alter_table("catalog_imports") as batch:
        batch.alter_column("status", existing_type=sa.String(16), server_default="running")
    for name, _, _ in reversed(COLUMNS):
        op.drop_column("catalog_imports", name)
