"""Category scope for promotion codes; existing codes keep catalog-wide scope."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'fa3d7b2e1c90'
down_revision = 'f9b6d4e20c83'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('promo_codes', sa.Column(
        'category_ids', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'),
        nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column('promo_codes', 'category_ids')
