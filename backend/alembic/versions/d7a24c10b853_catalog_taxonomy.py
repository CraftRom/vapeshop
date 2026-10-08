"""Catalog hierarchy, persisted merchandising flags and one-time SKU repair.

Revision ID: d7a24c10b853
Revises: c6a72f19e301
"""
from alembic import op
import sqlalchemy as sa
import re

revision = 'd7a24c10b853'
down_revision = 'c6a72f19e301'
branch_labels = None
depends_on = None
SKU_RE = re.compile(r'^[A-Z0-9][A-Z0-9._-]{2,31}$')
CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade():
    bind = op.get_bind()
    op.create_table('subcategories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('categories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False))
    op.create_index('ix_subcategories_category_active', 'subcategories', ['category_id', 'is_active', 'sort_order'])
    bind.execute(sa.text('INSERT INTO subcategories (id, name, description, sort_order, is_active) SELECT id, name, description, sort_order, is_active FROM categories'))
    fk = next(f for f in sa.inspect(bind).get_foreign_keys('products') if f['constrained_columns'] == ['category_id'])
    with op.batch_alter_table('products', naming_convention=CONVENTION) as batch:
        batch.drop_constraint(fk['name'] or 'fk_products_category_id_categories', type_='foreignkey')
        batch.alter_column('category_id', existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key('fk_products_category_id_categories', 'categories', ['category_id'], ['id'], ondelete='SET NULL')
        batch.add_column(sa.Column('subcategory_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_products_subcategory_id_subcategories', 'subcategories', ['subcategory_id'], ['id'], ondelete='SET NULL')
        batch.add_column(sa.Column('external_sku', sa.String(255), nullable=True))
        batch.add_column(sa.Column('is_new', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('is_sale', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_index('ix_products_external_sku', ['external_sku'])
        batch.create_index('ix_products_subcategory_active', ['subcategory_id', 'is_active', 'sort_order'])
    bind.execute(sa.text('UPDATE products SET subcategory_id = category_id, category_id = NULL'))
    bind.execute(sa.text('UPDATE products SET is_sale = :yes WHERE old_price > price'), {'yes': True})
    bind.execute(sa.text('DELETE FROM categories'))
    if bind.dialect.name == 'postgresql':
        bind.execute(sa.text("SELECT setval(pg_get_serial_sequence('subcategories', 'id'), COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM subcategories"))
    rows = bind.execute(sa.text('SELECT id, sku FROM products ORDER BY id')).all()
    # Reserve canonical articles first so normalizing an earlier row cannot steal one.
    used = {sku for _, sku in rows if sku and SKU_RE.fullmatch(sku)}
    for pid, raw in rows:
        if raw and SKU_RE.fullmatch(raw):
            continue
        canonical = str(raw or '').strip().upper()
        if not SKU_RE.fullmatch(canonical) or canonical in used:
            canonical = f'ELF-LEG-{pid:08d}'
            suffix = 0
            while canonical in used:
                suffix += 1
                canonical = f'ELF-LEG-{pid:08d}-{suffix}'
        used.add(canonical)
        bind.execute(sa.text('UPDATE products SET sku=:sku, external_sku=:old WHERE id=:id'),
                     {'sku': canonical, 'old': str(raw)[:255] if raw else None, 'id': pid})


def downgrade():
    bind = op.get_bind()
    # A populated catalog needs a database backup for a lossless rollback.
    changed = bind.scalar(sa.text('SELECT COUNT(*) FROM categories')) or bind.scalar(sa.text('SELECT COUNT(*) FROM products')) or bind.scalar(sa.text('SELECT COUNT(*) FROM subcategories'))
    if changed:
        raise RuntimeError('Каталог уже використовує нову структуру. Відновіть резервну копію для повернення старої схеми.')
    bind.execute(sa.text('INSERT INTO categories (id, name, description, sort_order, is_active) SELECT id, name, description, sort_order, is_active FROM subcategories'))
    bind.execute(sa.text('UPDATE products SET category_id=subcategory_id'))
    with op.batch_alter_table('products', naming_convention=CONVENTION) as batch:
        batch.drop_index('ix_products_external_sku')
        batch.drop_index('ix_products_subcategory_active')
        batch.drop_constraint('fk_products_subcategory_id_subcategories', type_='foreignkey')
        batch.drop_constraint('fk_products_category_id_categories', type_='foreignkey')
        batch.drop_column('subcategory_id')
        batch.drop_column('external_sku')
        batch.drop_column('is_new')
        batch.drop_column('is_sale')
        batch.alter_column('category_id', existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key('fk_products_category_id_categories', 'categories', ['category_id'], ['id'], ondelete='CASCADE')
    op.drop_table('subcategories')
