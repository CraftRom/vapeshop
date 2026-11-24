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


def head_baseline(postgres, revision='fb4a8c2d1e70'):
    # Additive revisions are tested against the revision they follow. Older
    # data-dependent migrations cannot all be rendered in Alembic offline mode.
    postgres(f"""
        CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY);
        INSERT INTO alembic_version VALUES ('{revision}');
    """)


def test_catalog_import_receipts_upgrade_and_downgrade(postgres):
    head_baseline(postgres)
    postgres(upgrade_sql('fb4a8c2d1e70:d7e3a91c5b20'))
    result=postgres("""
        INSERT INTO catalog_imports (digest,created_at) VALUES ('a',now());
        SELECT version_num FROM alembic_version;
        SELECT status FROM catalog_imports;
    """)
    assert 'd7e3a91c5b20' in result.stdout and 'status = "running"' in result.stdout
    duplicate=postgres("INSERT INTO catalog_imports (digest,created_at) VALUES ('a',now());",expect_error=True)
    assert 'catalog_imports_pkey' in duplicate.stderr
    downgrade=subprocess.run([sys.executable,'-m','alembic','downgrade','d7e3a91c5b20:fb4a8c2d1e70','--sql'],
        cwd=BACKEND,env={**os.environ,'PYTHONPATH':str(BACKEND),'DATABASE_URL':'postgresql+asyncpg://qa:qa@localhost/qa'},
        text=True,capture_output=True,timeout=30)
    assert downgrade.returncode==0,downgrade.stderr
    postgres(downgrade.stdout)
    result=postgres("SELECT to_regclass('public.catalog_imports') IS NULL AS gone; SELECT version_num FROM alembic_version;")
    assert 'gone = "t"' in result.stdout and 'fb4a8c2d1e70' in result.stdout


def test_durable_import_jobs_migration_keeps_applied_receipts(postgres):
    head_baseline(postgres)
    postgres(upgrade_sql('fb4a8c2d1e70:d7e3a91c5b20'))
    postgres("""
        INSERT INTO catalog_imports (digest,status,result,created_at) VALUES ('applied','running','{"rows":1}',now());
        INSERT INTO catalog_imports (digest,status,result,created_at) VALUES ('interrupted','running','',now());
    """)
    postgres(upgrade_sql('d7e3a91c5b20:head'))
    result=postgres("SELECT digest,status,rows_done,attempts FROM catalog_imports ORDER BY digest; SELECT version_num FROM alembic_version;")
    assert 'digest = "applied"' in result.stdout and 'status = "done"' in result.stdout
    assert 'interrupted' not in result.stdout and 'a3d9b6e14f02' in result.stdout
    postgres("INSERT INTO catalog_imports (digest,created_at,payload,rows_total) VALUES ('queued-job',now(),'[]',0);")
    assert 'status = "queued"' in postgres("SELECT status FROM catalog_imports WHERE digest='queued-job';").stdout
    downgrade=subprocess.run([sys.executable,'-m','alembic','downgrade','a3d9b6e14f02:d7e3a91c5b20','--sql'],
        cwd=BACKEND,env={**os.environ,'PYTHONPATH':str(BACKEND),'DATABASE_URL':'postgresql+asyncpg://qa:qa@localhost/qa'},
        text=True,capture_output=True,timeout=30)
    assert downgrade.returncode==0,downgrade.stderr
    postgres(downgrade.stdout)
    result=postgres("SELECT digest FROM catalog_imports; SELECT version_num FROM alembic_version;")
    assert 'applied' in result.stdout and 'queued-job' not in result.stdout and 'd7e3a91c5b20' in result.stdout


def test_commerce_channel_and_queue_expressions_on_real_postgres(postgres):
    from sqlalchemy import select,func
    from sqlalchemy.dialects import postgresql
    from shop.services.commerce_workspace import channel_expression,queue_condition
    from shop import models as m
    postgres("""
        CREATE TABLE orders (id INTEGER PRIMARY KEY,status VARCHAR(32),business_state VARCHAR(16),
            tracking_number VARCHAR(64),attribution JSONB,crm_snapshot JSONB);
        INSERT INTO orders (id,status,business_state,tracking_number,attribution) VALUES
            (1,'NEW','pending',NULL,'{"source":"google","channel":"telegram_bot"}'),
            (2,'NEW','pending',NULL,'{"source":"telegram_bot","channel":"telegram_miniapp"}'),
            (3,'ACCEPTED','pending','20450000123456','{"source":"instagram"}'),
            (4,'NEW','refusal',NULL,'{"source":"telegram_bot"}');
        INSERT INTO orders VALUES (5,'NEW','pending',NULL,NULL,'{"utm":{"source":"telegram_bot"}}');
    """)
    for key in ['miniapp','bot','unknown']:
        statement=select(func.count().label('matched')).select_from(m.Order).where(queue_condition('open'),channel_expression()==key)
        sql=str(statement.compile(dialect=postgresql.dialect(),compile_kwargs={'literal_binds':True}))
        expected=2 if key=='bot' else 1
        assert f'matched = "{expected}"' in postgres(sql).stdout
