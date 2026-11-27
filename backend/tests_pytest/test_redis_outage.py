"""Redis outage from the production log of 26.11: no orphaned DNS futures, no warning spam."""
import asyncio
import gc
import logging
import socket

import pytest

from shop import redis_dns
from shop.services import salesdrive_reconciler as reconciler


@pytest.mark.asyncio
async def test_slow_failing_lookup_is_consumed_after_the_timeout(monkeypatch):
    loop = asyncio.get_running_loop()
    orphaned = []
    loop.set_exception_handler(lambda _loop, context: orphaned.append(context))

    async def slow_failure(host, port, *args, **kwargs):
        await asyncio.sleep(0.05)
        raise socket.gaierror(-3, 'Temporary failure in name resolution')
    monkeypatch.setattr(loop, 'getaddrinfo', slow_failure)
    with pytest.raises(ConnectionError, match='не резолвиться'):
        await redis_dns.ensure_resolvable('redis://:secret@redis:6379/0', timeout=0.01)
    await asyncio.sleep(0.1)  # the lookup finishes after we stopped waiting
    gc.collect()
    await asyncio.sleep(0)
    loop.set_exception_handler(None)
    assert orphaned == [], 'no "Future exception was never retrieved"'


@pytest.mark.asyncio
async def test_immediate_failure_and_literal_addresses(monkeypatch):
    loop = asyncio.get_running_loop()

    async def failing(host, port, *args, **kwargs):
        raise socket.gaierror(-2, 'Name or service not known')
    monkeypatch.setattr(loop, 'getaddrinfo', failing)
    with pytest.raises(ConnectionError):
        await redis_dns.ensure_resolvable('redis://redis:6379/0')
    await redis_dns.ensure_resolvable('redis://127.0.0.1:6379/0')  # IP: no lookup at all


@pytest.mark.asyncio
async def test_lease_outage_is_logged_once_then_throttled_and_recovery_once(monkeypatch, caplog):
    monkeypatch.setattr(reconciler, '_redis_url', lambda: 'redis://redis:6379/0')
    monkeypatch.setattr(reconciler, '_lease_outage', {'since': 0.0, 'logged': 0.0, 'suppressed': 0})

    async def down(url, timeout=0.5):
        raise ConnectionError('Redis host redis не резолвиться')
    monkeypatch.setattr(redis_dns, 'ensure_resolvable', down)
    caplog.set_level(logging.INFO, logger=reconciler.log.name)
    for _ in range(5):
        assert (await reconciler._claim_lease())[2] == 'redis_unavailable'
    failed = [r for r in caplog.records if getattr(r, 'event', '') == 'salesdrive.reconcile.lease_failed']
    assert len(failed) == 1 and 'не резолвиться' in failed[0].getMessage()
    assert reconciler._lease_outage['suppressed'] == 4

    reconciler._lease_outage['logged'] -= reconciler.LEASE_LOG_INTERVAL_SECONDS + 1
    await reconciler._claim_lease()
    failed = [r for r in caplog.records if getattr(r, 'event', '') == 'salesdrive.reconcile.lease_failed']
    assert len(failed) == 2 and 'ще 4 таких спроб' in failed[1].getMessage()

    reconciler._lease_recovered()
    reconciler._lease_recovered()
    recovered = [r for r in caplog.records if getattr(r, 'event', '') == 'salesdrive.reconcile.lease_recovered']
    assert len(recovered) == 1 and reconciler._lease_outage['since'] == 0.0
