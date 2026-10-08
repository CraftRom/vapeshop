"""Run migration detection on real database version records."""
import asyncio
from tempfile import TemporaryDirectory
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from shop.catalog_upgrade import needs_catalog_upgrade
from qa_common import Report
r=Report('CATALOG DEPLOY')
async def main():
 with TemporaryDirectory() as directory:
  url='sqlite+aiosqlite:///'+str(Path(directory)/'catalog.db')
  r.check(not await needs_catalog_upgrade(url),'чиста база не потребує зупинки старих застосунків')
  engine=create_async_engine(url)
  async with engine.begin() as conn:
   await conn.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32))'))
   await conn.execute(text("INSERT INTO alembic_version VALUES ('c6a72f19e301')"))
  r.check(await needs_catalog_upgrade(url),'старий каталог потребує узгодженого оновлення')
  async with engine.begin() as conn:
   await conn.execute(text("UPDATE alembic_version SET version_num='d7a24c10b853'"))
  r.check(not await needs_catalog_upgrade(url),'повторний реліз не повторює зупинку для вже застосованої міграції')
  await engine.dispose()
 script=(Path(__file__).resolve().parents[2]/'deploy/deploy.sh').read_text()
 transition=script[script.index('CATALOG_BREAKING_UPGRADE="$'):script.index('"${COMPOSE[@]}" run --rm migrate')]
 r.check('BACKUP_CREATED' in transition and transition.index('BACKUP_CREATED')<transition.index('stop api bot scheduler') and 'exit 1' in transition,'без успішного бекапу перехід зупиняється до вимкнення старих застосунків')
 r.check(script.index('stop api bot scheduler')<script.index('run --rm migrate'),'старі API, бот і scheduler зупиняються перед зміною схеми')
 guard=script[script.index('rollback_core_runtime()'):script.index('echo "==> ФАЗА 1/6')]
 r.check('CATALOG_BREAKING_UPGRADE' in guard and guard.index('CATALOG_BREAKING_UPGRADE')<guard.index('docker tag'),'відкат старих образів заблоковано після несумісної міграції')
asyncio.run(main()); raise SystemExit(bool(r.done()))
