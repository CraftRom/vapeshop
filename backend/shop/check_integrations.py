"""python -m shop.check_integrations [--live]: read-only, secret-free JSON report."""
import argparse
import asyncio
import json
from shop.repo.factory import open_repo
from shop.db import engine
from shop.services.integration_health import inspect_integrations


async def run(live):
    try:
        async with open_repo() as repo:
            result = await inspect_integrations(repo, live=live)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['errors'] else 0
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Perform read-only provider requests with configured keys')
    raise SystemExit(asyncio.run(run(parser.parse_args().live)))
