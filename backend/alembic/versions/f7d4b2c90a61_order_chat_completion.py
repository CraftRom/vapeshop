"""Persist completion time for the shared after-sales chat policy."""
from alembic import op
import sqlalchemy as sa

revision = 'f7d4b2c90a61'
down_revision = 'f6b3a8d21c90'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orders', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_orders_completed_at', 'orders', ['completed_at'])
    # Historical exact completion is unavailable. CRM result time is the best
    # existing evidence; legacy updated_at is an explicit one-time estimate.
    orders = sa.table('orders', sa.column('status'), sa.column('business_state'),
                      sa.column('business_state_at'), sa.column('updated_at'),
                      sa.column('created_at'), sa.column('completed_at'))
    # orders.status is PostgreSQL's native `orderstatus` ENUM, not VARCHAR.
    # Alembic's lightweight sa.table() declares columns as NullType unless a
    # type is specified; `status.in_(...)` therefore binds VARCHAR parameters.
    # PostgreSQL rejects `orderstatus = character varying` (asyncpg).
    # Cast the *column* to VARCHAR for this one-off historical backfill.  It
    # also works with SQLite and does not change the column or stored statuses.
    status_text = sa.cast(orders.c.status, sa.String())
    op.execute(orders.update().where(sa.or_(status_text.in_(['DONE', 'CANCELLED']),
                    orders.c.business_state.in_(['sale', 'refusal']))).values(
        completed_at=sa.case((orders.c.business_state.in_(['sale', 'refusal']),
                 sa.func.coalesce(orders.c.business_state_at, orders.c.updated_at, orders.c.created_at)),
                 else_=sa.func.coalesce(orders.c.updated_at, orders.c.created_at))))


def downgrade():
    op.drop_index('ix_orders_completed_at', table_name='orders')
    op.drop_column('orders', 'completed_at')
