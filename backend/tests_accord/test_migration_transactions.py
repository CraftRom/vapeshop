"""Enum changes must commit before later revisions consume the new value.

Set QA_POSTGRES_BIN to a PostgreSQL bin directory to also execute the generated
SQL against a temporary, real PostgreSQL cluster in single-user mode. This
requires no network sockets and never connects to an existing database.
"""
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
POSTGRES_BIN = os.environ.get('QA_POSTGRES_BIN')


def upgrade_sql(revision):
    result = subprocess.run(
        [sys.executable, '-m', 'alembic', 'upgrade', revision, '--sql'],
        cwd=BACKEND, env={**os.environ, 'PYTHONPATH': str(BACKEND),
                         'DATABASE_URL': 'postgresql+asyncpg://qa:qa@localhost/qa'},
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_new_enum_value_is_committed_before_status_backfill():
    sql = upgrade_sql('a9d4e77b1c60')
    addition = sql.index("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'ACCEPTED'")
    backfill = sql.index("UPDATE orders SET status = 'ACCEPTED'")
    assert 'COMMIT;' in sql[addition:backfill]
    assert sql[addition:backfill].count('BEGIN;') >= 1
    assert sql.count('BEGIN;') == sql.count('COMMIT;') == 8


@pytest.fixture
def postgres(tmp_path):
    if not POSTGRES_BIN:
        pytest.skip('QA_POSTGRES_BIN is required for real PostgreSQL execution')
    binaries, data = Path(POSTGRES_BIN), tmp_path / 'pgdata'
    result = subprocess.run([str(binaries / 'initdb'), '-D', str(data), '-U', 'postgres',
                             '--no-locale', '--encoding=UTF8', '--auth=trust'],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr

    def execute(sql, expect_error=False):
        # -j reads commands through blank-line separators, preserving SQL lines.
        result = subprocess.run([str(binaries / 'postgres'), '--single', '-j',
                                 '-D', str(data), 'postgres'], input=sql + '\n\n',
                                text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        if not expect_error:
            assert not re.search(r'\b(?:ERROR|FATAL|PANIC):', result.stderr), result.stderr
        return result

    return execute


def test_real_postgres_reproduces_original_failure(postgres):
    sql = upgrade_sql('a9d4e77b1c60')
    single_transaction = 'BEGIN;\n' + sql.replace('BEGIN;', '').replace('COMMIT;', '') + '\nCOMMIT;'
    result = postgres(single_transaction, expect_error=True)
    assert 'unsafe use of new value "ACCEPTED"' in result.stderr


def test_real_postgres_fresh_database_passes_backfill(postgres):
    postgres(upgrade_sql('a9d4e77b1c60'))
    result = postgres('SELECT version_num FROM alembic_version;')
    assert 'a9d4e77b1c60' in result.stdout


def test_real_postgres_existing_order_is_preserved_and_converted(postgres):
    postgres(upgrade_sql('c7e2b8f41a09'))
    postgres("""
        INSERT INTO users (id, tg_id, age_confirmed, is_blocked, referral_code,
            bonus_balance, orders_count, total_spent, referrals_count, search_key)
        VALUES (1, 1, false, false, 'MIGRATION-QA', 0, 0, 0, 0, 'qa');
        INSERT INTO orders (id, user_id, status, subtotal, discount, bonus_used,
                            total, referral_paid, search_key)
        VALUES (1, 1, 'CONFIRMED', 100, 0, 0, 100, false, 'qa');
    """)
    postgres(upgrade_sql('c7e2b8f41a09:a9d4e77b1c60'))
    result = postgres('SELECT id, status, total FROM orders;')
    assert 'status = "ACCEPTED"' in result.stdout
    assert 'total = "100.00"' in result.stdout
    assert 'id = "1"' in result.stdout
