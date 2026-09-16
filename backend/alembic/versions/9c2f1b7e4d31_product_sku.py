"""Product SKU
Revision ID: 9c2f1b7e4d31
Revises: a9d4e77b1c60
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
revision='9c2f1b7e4d31'; down_revision='a7c3e1f5d2b9'; branch_labels=None; depends_on=None

def upgrade():
    op.add_column('products', sa.Column('sku', sa.String(32), nullable=True))
    # Existing rows receive stable legacy SKUs before NOT NULL/UNIQUE is enabled.
    op.execute("UPDATE products SET sku = 'ELF-LEG-' || LPAD(id::text, 8, '0') WHERE sku IS NULL")
    op.alter_column('products','sku',nullable=False)
    op.create_index('ux_products_sku','products',['sku'],unique=True)

def downgrade():
    op.drop_index('ux_products_sku', table_name='products'); op.drop_column('products','sku')
