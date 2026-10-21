"""Apply real new migration over a legacy SQLite table and inspect PostgreSQL DDL."""
import importlib.util
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic.migration import MigrationContext
from alembic.operations import Operations
from qa_common import Report
r=Report('SUPPORT REQUEST MIGRATION')
file=Path(__file__).resolve().parents[1]/'alembic/versions/f8a5c3d10b72_support_client_requests.py'
spec=importlib.util.spec_from_file_location('support_migration',file);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
engine=sa.create_engine('sqlite://')
with engine.begin() as conn:
 conn.execute(sa.text('CREATE TABLE support_messages (id INTEGER PRIMARY KEY, thread_id INTEGER NOT NULL, text TEXT)'))
 conn.execute(sa.text("INSERT INTO support_messages(id,thread_id,text) VALUES (1,1,'old')"))
 migration.op=Operations(MigrationContext.configure(conn));migration.upgrade()
 r.check('client_request_id' in {c['name'] for c in sa.inspect(conn).get_columns('support_messages')},'upgrade adds nullable request key')
 r.check(conn.execute(sa.text('SELECT text,client_request_id FROM support_messages WHERE id=1')).one()==('old',None),'legacy message preserved')
 conn.execute(sa.text("INSERT INTO support_messages(id,thread_id,text,client_request_id) VALUES(2,1,'new','same')"))
 try:
  conn.execute(sa.text("INSERT INTO support_messages(id,thread_id,text,client_request_id) VALUES(3,1,'duplicate','same')"));unique=False
 except sa.exc.IntegrityError:unique=True
 r.check(unique,'same thread/key cannot be inserted twice')
 conn.execute(sa.text("INSERT INTO support_messages(id,thread_id,text,client_request_id) VALUES(4,2,'other','same'),(5,1,'legacy',NULL)"))
 r.check(conn.execute(sa.text('SELECT COUNT(*) FROM support_messages')).scalar()==4,'different threads and NULL legacy keys remain valid')
 migration.downgrade()
 r.check('client_request_id' not in {c['name'] for c in sa.inspect(conn).get_columns('support_messages')},'downgrade removes new schema')
 r.check(conn.execute(sa.text('SELECT COUNT(*) FROM support_messages')).scalar()==4,'downgrade preserves history')
t=sa.Table('support_messages',sa.MetaData(),sa.Column('thread_id',sa.Integer),sa.Column('client_request_id',sa.String(64)))
index=sa.Index('uq_support_messages_client_request',t.c.thread_id,t.c.client_request_id,unique=True)
ddl=str(sa.schema.CreateIndex(index).compile(dialect=postgresql.dialect()))
r.check('CREATE UNIQUE INDEX' in ddl and 'thread_id, client_request_id' in ddl,'unique index compiles for PostgreSQL')
r.check(migration.down_revision=='f7d4b2c90a61','migration continues previous hotfix chain')
engine.dispose()
raise SystemExit(bool(r.done()))
