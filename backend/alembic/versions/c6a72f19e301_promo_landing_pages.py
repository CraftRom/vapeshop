"""promo landing page builder and aggregate analytics

Revision ID: c6a72f19e301
Revises: b8f2c6d4a910
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c6a72f19e301"
down_revision = "b8f2c6d4a910"
branch_labels = None
depends_on = None

JSON = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "promo_landing_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("draft_config", JSON, nullable=False),
        sa.Column("published_config", JSON, nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("domain", name="uq_promo_landing_pages_domain"),
    )
    op.create_index("ix_promo_landing_pages_domain", "promo_landing_pages", ["domain"], unique=True)
    op.create_index("ix_promo_landing_pages_is_published", "promo_landing_pages", ["is_published"])

    op.create_table(
        "promo_landing_daily_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["page_id"], ["promo_landing_pages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("page_id", "day", name="uq_promo_landing_stat_day"),
    )
    op.create_index("ix_promo_landing_stats_page_day", "promo_landing_daily_stats", ["page_id", "day"])


def downgrade() -> None:
    op.drop_index("ix_promo_landing_stats_page_day", table_name="promo_landing_daily_stats")
    op.drop_table("promo_landing_daily_stats")
    op.drop_index("ix_promo_landing_pages_is_published", table_name="promo_landing_pages")
    op.drop_index("ix_promo_landing_pages_domain", table_name="promo_landing_pages")
    op.drop_table("promo_landing_pages")
