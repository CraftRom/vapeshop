"""Content migration over populated legacy broadcasts and PostgreSQL SQL compilation."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from qa_common import Report
r=Report('Broadcast content migration')
with tempfile.TemporaryDirectory(prefix='broadcast-migration-') as temp:
 path=Path(temp)/'legacy.db'
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE broadcasts (id INTEGER PRIMARY KEY, text TEXT, sent_count INTEGER)')
  db.execute("INSERT INTO broadcasts VALUES (1, '<b>Legacy</b>', 7)")
 env={**os.environ,'DATABASE_URL':f'sqlite+aiosqlite:///{path}'}
 def alembic(*args, env=env):
  return subprocess.run([sys.executable,'-m','alembic',*args],env=env,check=True,capture_output=True,text=True).stdout
 alembic('stamp','fa3d7b2e1c90');alembic('upgrade','fb4a8c2d1e70')
 with sqlite3.connect(path) as db:
  r.check(db.execute('SELECT text,sent_count,text_format,client_key FROM broadcasts').fetchone()==('<b>Legacy</b>',7,'html',None),'existing HTML and delivery counters preserved')
  db.execute("INSERT INTO broadcasts(id,text,sent_count,client_key) VALUES(2,'new',0,'same-key')")
  try:
   db.execute("INSERT INTO broadcasts(id,text,sent_count,client_key) VALUES(3,'duplicate',0,'same-key')")
   unique=False
  except sqlite3.IntegrityError:unique=True
  r.check(unique,'creation key protected by unique database index')
  db.execute("INSERT INTO broadcasts(id,text,sent_count) VALUES(4,'old writer',0),(5,'old writer',0)")
  r.check(db.execute('SELECT text_format FROM broadcasts WHERE id=4').fetchone()[0]=='html','older writers keep HTML compatibility')
  r.check(db.execute('SELECT COUNT(*) FROM broadcasts WHERE client_key IS NULL').fetchone()[0]==3,'legacy NULL keys remain valid')
 alembic('downgrade','fa3d7b2e1c90')
 with sqlite3.connect(path) as db:
  columns={row[1] for row in db.execute('PRAGMA table_info(broadcasts)')}
  r.check('text_format' not in columns and 'client_key' not in columns,'downgrade removes only added schema')
  r.check(db.execute('SELECT text,sent_count FROM broadcasts WHERE id=1').fetchone()==('<b>Legacy</b>',7),'downgrade preserves old content and counters')
 sql=alembic('upgrade','fa3d7b2e1c90:fb4a8c2d1e70','--sql',env={**env,'DATABASE_URL':'postgresql+asyncpg://qa:qa@127.0.0.1/qa'})
 r.check("text_format VARCHAR(8) DEFAULT 'html' NOT NULL" in sql and 'CREATE UNIQUE INDEX uq_broadcasts_client_key' in sql,'PostgreSQL DDL includes compatible default and idempotency index')
raise SystemExit(bool(r.done()))
