"""The Redis client against a real redis-server: lease, live order events, health.

Runs where a redis-server binary exists (skipped otherwise). It guards
redis-py upgrades: every call the shop makes is exercised for real.
"""
import asyncio
import shutil
import socket
import subprocess
import time

import pytest
import pytest_asyncio

from shop.config import settings
from shop.services import realtime, salesdrive_reconciler

SERVER = shutil.which('redis-server')
pytestmark = pytest.mark.skipif(SERVER is None, reason='redis-server is not installed')
PASSWORD = 'qa-redis-secret'


@pytest_asyncio.fixture
async def redis_url(tmp_path, monkeypatch):
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
    process = subprocess.Popen([SERVER, '--port', str(port), '--bind', '127.0.0.1', '--requirepass', PASSWORD,
                                '--save', '', '--appendonly', 'no', '--dir', str(tmp_path)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(('127.0.0.1', port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.05)
    url = f'redis://:{PASSWORD}@127.0.0.1:{port}/0'
    monkeypatch.setattr(settings, 'redis_url', url, raising=False)
    yield url
    process.terminate(); process.wait(timeout=5)


@pytest.mark.asyncio
async def test_lease_is_claimed_once(redis_url):
    client, token, reason = await salesdrive_reconciler._claim_lease()
    assert reason is None and token
    try:
        assert (await salesdrive_reconciler._claim_lease())[2] == 'lease_busy'
        assert await client.get(salesdrive_reconciler.LEASE_KEY) == token
        assert 0 < await client.ttl(salesdrive_reconciler.LEASE_KEY) <= salesdrive_reconciler.LEASE_SECONDS
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_order_event_travels_through_pubsub(redis_url):
    events = realtime.subscribe_order_events()

    async def first_event():
        async for item in events:  # None is the stream's heartbeat
            if item is not None:
                return item
    received = asyncio.create_task(first_event())
    await asyncio.sleep(0.3)  # the subscription is in place
    await realtime.publish_order_changed(41, user_id=7, fields=('status',))
    payload = await asyncio.wait_for(received, 5)
    assert payload['orderId'] == 41
    await events.aclose()


@pytest.mark.asyncio
async def test_health_check_pings(redis_url):
    from api.routers import system
    assert (await system._redis()) == {'configured': True, 'ok': True}


@pytest.mark.asyncio
async def test_wrong_password_is_reported_not_raised(redis_url, monkeypatch):
    monkeypatch.setattr(settings, 'redis_url', redis_url.replace(PASSWORD, 'wrong'), raising=False)
    from api.routers import system
    result = await system._redis()
    assert result['configured'] is True and result['ok'] is False
    assert (await salesdrive_reconciler._claim_lease())[2] == 'redis_unavailable'
