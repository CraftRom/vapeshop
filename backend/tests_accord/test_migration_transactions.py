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


def blog_baseline(postgres):
    # Test this additive revision against its required existing tables. Older
    # data-dependent migrations cannot all be rendered in Alembic offline mode.
    postgres("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, bonus_balance NUMERIC(12,2),
            orders_count INTEGER, total_spent NUMERIC(12,2));
        CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY);
        INSERT INTO alembic_version VALUES ('bc1a8f723f9d');
    """)


def test_blog_migration_on_postgres_and_versioned_updates(postgres):
    blog_baseline(postgres)
    postgres(upgrade_sql('bc1a8f723f9d:head'))
    result=postgres("""
        INSERT INTO blog_posts (slug,title,body,search_text,status,published_at,created_by,updated_by)
        VALUES ('journal','Журнал','Повний текст статті','журнал','published',now(),'owner','owner');
        INSERT INTO blog_slugs (slug,post_id) VALUES ('journal',1);
        INSERT INTO blog_comments (post_id,author_name,body,is_staff,status,client_key)
        VALUES (1,'Редакція','Відповідь',true,'approved','retry-key');
        UPDATE blog_posts SET title='Збережена версія',version=version+1 WHERE id=1 AND version=1;
        UPDATE blog_posts SET title='Застаріла версія',version=version+1 WHERE id=1 AND version=1;
        SELECT version_num FROM alembic_version;
        SELECT title,version FROM blog_posts;
    """)
    assert 'c04b19a7e230' in result.stdout
    assert 'title = "Збережена версія"' in result.stdout
    assert 'version = "2"' in result.stdout
    duplicate=postgres("INSERT INTO blog_comments (post_id,author_name,body,client_key) VALUES (1,'Другий','Дубль','retry-key');",expect_error=True)
    assert 'uq_blog_comment_retry' in duplicate.stderr
    orphan=postgres("INSERT INTO blog_comments (post_id,parent_id,author_name,body) VALUES (1,999,'Автор','Текст');",expect_error=True)
    assert 'foreign key constraint' in orphan.stderr


def test_blog_upgrade_and_downgrade_leave_existing_customers_untouched(postgres):
    blog_baseline(postgres)
    postgres("""
        INSERT INTO users (id,bonus_balance,orders_count,total_spent)
        VALUES (987,37,3,1500);
    """)
    postgres(upgrade_sql('bc1a8f723f9d:head'))
    result=postgres('SELECT id,bonus_balance,orders_count,total_spent FROM users WHERE id=987;')
    assert 'bonus_balance = "37.00"' in result.stdout
    assert 'orders_count = "3"' in result.stdout
    assert 'total_spent = "1500.00"' in result.stdout
    downgrade=subprocess.run([sys.executable,'-m','alembic','downgrade','c04b19a7e230:bc1a8f723f9d','--sql'],
        cwd=BACKEND,env={**os.environ,'PYTHONPATH':str(BACKEND),'DATABASE_URL':'postgresql+asyncpg://qa:qa@localhost/qa'},
        text=True,capture_output=True,timeout=30)
    assert downgrade.returncode==0,downgrade.stderr
    postgres(downgrade.stdout)
    result=postgres('SELECT id,bonus_balance FROM users WHERE id=987; SELECT version_num FROM alembic_version;')
    assert 'id = "987"' in result.stdout
    assert 'bc1a8f723f9d' in result.stdout


def test_commerce_channel_and_queue_expressions_on_real_postgres(postgres):
    from sqlalchemy import select,func
    from sqlalchemy.dialects import postgresql
    from shop.services.commerce_workspace import channel_expression,queue_condition
    from shop import models as m
    postgres("""
        CREATE TABLE orders (id INTEGER PRIMARY KEY,status VARCHAR(32),business_state VARCHAR(16),
            tracking_number VARCHAR(64),attribution JSONB,crm_snapshot JSONB);
        INSERT INTO orders (id,status,business_state,tracking_number,attribution) VALUES
            (1,'NEW','pending',NULL,'{"source":"google","channel":"accord_website"}'),
            (2,'NEW','pending',NULL,'{"source":"accord_website","channel":"telegram_miniapp"}'),
            (3,'ACCEPTED','pending','20450000123456','{"source":"telegram_bot"}'),
            (4,'NEW','refusal',NULL,'{"source":"accord_website"}');
        INSERT INTO orders VALUES (5,'NEW','pending',NULL,NULL,'{"utm":{"source":"accord_website"}}');
    """)
    for key in ['website','miniapp','bot']:
        statement=select(func.count().label('matched')).select_from(m.Order).where(queue_condition('open'),channel_expression()==key)
        sql=str(statement.compile(dialect=postgresql.dialect(),compile_kwargs={'literal_binds':True}))
        expected=2 if key=='website' else 1
        assert f'matched = "{expected}"' in postgres(sql).stdout
