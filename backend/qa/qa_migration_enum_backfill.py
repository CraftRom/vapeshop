"""Regression for PostgreSQL native ENUM bindings in f7d4b2c90a61.

Does not claim to substitute for a live PostgreSQL migration. Run with:
    python qa/qa_migration_enum_backfill.py
"""
from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from alembic.migration import MigrationContext
from alembic.operations import Operations


REVISION = (Path(__file__).resolve().parents[1] / 'alembic' / 'versions' /
            'f7d4b2c90a61_order_chat_completion.py')


def migration():
    spec = importlib.util.spec_from_file_location('f7d4b2c90a61', REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationBackfillTests(TestCase):
    def test_asyncpg_compilation_uses_explicit_cast(self):
        module = migration()
        with patch.object(module.op, 'add_column'), patch.object(module.op, 'create_index'), \
                patch.object(module.op, 'execute') as execute:
            module.upgrade()
        statement = execute.call_args.args[0]
        sql = str(statement.compile(dialect=PGDialect_asyncpg(),
                                    compile_kwargs={'render_postcompile': True}))
        self.assertIn('CAST(orders.status AS VARCHAR) IN', sql)
        self.assertNotIn('WHERE orders.status IN', sql)
        # `business_state` has VARCHAR storage and may be compared to VARCHAR.
        self.assertIn('orders.business_state IN', sql)
        self.assertIn('UPDATE orders SET completed_at=', sql)

    def test_sqlite_upgrade_backfills_only_final_orders_and_downgrades(self):
        engine = sa.create_engine('sqlite:///:memory:')
        with engine.begin() as c:
            c.execute(sa.text('''CREATE TABLE orders (
                 id INTEGER PRIMARY KEY, status VARCHAR(16), business_state VARCHAR(16),
                 business_state_at DATETIME, updated_at DATETIME, created_at DATETIME)'''))
            c.execute(sa.text('''INSERT INTO orders VALUES
                (1, 'DONE', 'sale', '2026-10-12 10:00:00', '2026-10-13 10:00:00', '2026-09-01 10:00:00'),
                (2, 'CANCELLED', 'pending', NULL, '2026-10-11 10:00:00', '2026-09-01 10:00:00'),
                (3, 'NEW', 'pending', NULL, '2026-10-13 10:00:00', '2026-10-13 10:00:00'),
                (4, 'SHIPPED', 'refusal', '2026-10-10 09:00:00', '2026-10-13 10:00:00', '2026-09-01 10:00:00'),
                (5, 'DONE', 'pending', NULL, NULL, '2026-09-01 10:00:00')'''))
            with Operations.context(MigrationContext.configure(c)):
                migration().upgrade()
            rows = c.execute(sa.text('SELECT id, completed_at FROM orders ORDER BY id')).all()
            self.assertEqual(rows, [
                (1, '2026-10-12 10:00:00'),
                (2, '2026-10-11 10:00:00'),
                (3, None),
                (4, '2026-10-10 09:00:00'),
                (5, '2026-09-01 10:00:00'),
            ])
            with Operations.context(MigrationContext.configure(c)):
                migration().downgrade()
            self.assertNotIn('completed_at', [x['name'] for x in sa.inspect(c).get_columns('orders')])
        engine.dispose()

    def test_pg_offline_ddl_mentions_safe_status_cast(self):
        output = StringIO()
        with Operations.context(MigrationContext.configure(
                dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output})):
            migration().upgrade()
        sql = output.getvalue()
        self.assertIn('ALTER TABLE orders ADD COLUMN completed_at TIMESTAMP WITH TIME ZONE', sql)
        self.assertIn('CREATE INDEX ix_orders_completed_at', sql)
        self.assertIn('CAST(orders.status AS VARCHAR)', sql)
        self.assertIn('coalesce(orders.business_state_at, orders.updated_at, orders.created_at)', sql)


if __name__ == '__main__':
    main(verbosity=2)
