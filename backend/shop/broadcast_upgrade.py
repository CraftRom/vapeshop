"""Print 1 if old broadcast workers must be stopped before the queue migration."""
import asyncio
from sqlalchemy import inspect
from shop.db import engine


def needs_worker_stop(connection):
    inspector = inspect(connection)
    if not inspector.has_table("broadcasts"):
        return False
    return "lease_owner" not in {c["name"] for c in inspector.get_columns("broadcasts")}


async def main():
    async with engine.connect() as connection:
        print(int(await connection.run_sync(needs_worker_stop)))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
