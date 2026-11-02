"""Upgrade populated pre-scope data, and verify PostgreSQL migration SQL."""
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from qa_common import Report
r = Report('Promo category migration')
with tempfile.TemporaryDirectory(prefix='promo-migration-') as temp:
    path = Path(temp) / 'migration.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE promo_codes (id INTEGER PRIMARY KEY, code VARCHAR(32), used_count INTEGER)')
        connection.execute("INSERT INTO promo_codes VALUES (1, 'LEGACY', 7)")
    env = {**os.environ, 'DATABASE_URL': f'sqlite+aiosqlite:///{path}'}
    def alembic(*args, env=env):
        import sys
        return subprocess.run([sys.executable, '-m', 'alembic', *args], env=env, check=True, capture_output=True, text=True)
    alembic('stamp', 'f9b6d4e20c83')
    alembic('upgrade', 'head')
    with sqlite3.connect(path) as connection:
        row = connection.execute('SELECT code, used_count, category_ids FROM promo_codes').fetchone()
        r.check(row == ('LEGACY', 7, '[]'), 'existing codes keep usage and all-products scope')
        connection.execute("INSERT INTO promo_codes (id, code, used_count) VALUES (2, 'DEFAULT', 0)")
        r.check(connection.execute('SELECT category_ids FROM promo_codes WHERE id=2').fetchone()[0] == '[]', 'database default supports older writers')
        r.check(connection.execute('SELECT version_num FROM alembic_version').fetchone()[0] == 'fa3d7b2e1c90', 'migration records new head')
    alembic('downgrade', 'f9b6d4e20c83')
    with sqlite3.connect(path) as connection:
        r.check('category_ids' not in [row[1] for row in connection.execute('PRAGMA table_info(promo_codes)')], 'downgrade removes only new column')
        r.check(connection.execute('SELECT code, used_count FROM promo_codes WHERE id=1').fetchone() == ('LEGACY', 7), 'downgrade preserves original data')
    sql = alembic('upgrade', 'f9b6d4e20c83:head', '--sql', env={**env, 'DATABASE_URL': 'postgresql+asyncpg://qa:qa@127.0.0.1/qa'}).stdout
    r.check("category_ids JSONB DEFAULT '[]' NOT NULL" in sql, 'PostgreSQL DDL has non-null JSONB and safe legacy default')
raise SystemExit(bool(r.done()))
