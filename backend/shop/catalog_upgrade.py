"""Detect the one catalog migration that changes the meaning of category IDs."""
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

CATALOG_REVISION = 'd7a24c10b853'


async def needs_catalog_upgrade(database_url):
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            has_version = await connection.run_sync(lambda conn: inspect(conn).has_table('alembic_version'))
            if not has_version:
                return False  # Fresh installation has no old app data.
            current = list(await connection.scalars(text('SELECT version_num FROM alembic_version')))
        if not current:
            return False
        directory = Path(__file__).resolve().parents[1]
        config = Config(str(directory / 'alembic.ini'))
        config.set_main_option('script_location', str(directory / 'alembic'))
        script = ScriptDirectory.from_config(config)
        ancestors = {rev.revision for revision in current for rev in script.iterate_revisions(revision, 'base')}
        return CATALOG_REVISION not in ancestors
    finally:
        await engine.dispose()


if __name__ == '__main__':
    import asyncio
    from shop.config import settings
    print('1' if asyncio.run(needs_catalog_upgrade(settings.db_url)) else '0')
