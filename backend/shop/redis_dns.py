"""Resolve the Redis host before redis-py connects.

Production log 26.11 (Redis container unreachable for ~2 minutes): every
connection attempt timed out after 0.5 s, but the DNS lookup redis-py had
started kept running in the executor. When it finally failed with
``gaierror`` nobody awaited it, and asyncio logged an ERROR "Future
exception was never retrieved" about 20 s later — noise that looked like a
crash. Here the lookup always has an owner: its result is consumed even when
we stop waiting, and an unresolvable host becomes an ordinary
ConnectionError that callers already handle.
"""
from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlsplit


def _consume(future: asyncio.Future) -> None:
    if not future.cancelled():
        future.exception()


async def ensure_resolvable(url: str, timeout: float = 0.5) -> None:
    parts = urlsplit(url)
    host = parts.hostname
    if not host or parts.scheme == "unix":
        return
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    lookup = asyncio.ensure_future(loop.getaddrinfo(host, parts.port or 6379))
    lookup.add_done_callback(_consume)
    try:
        await asyncio.wait_for(asyncio.shield(lookup), timeout)
    except asyncio.TimeoutError:
        raise ConnectionError(f"Redis host {host} не резолвиться за {timeout} с") from None
    except OSError as exc:
        raise ConnectionError(f"Redis host {host} не резолвиться: {exc}") from None
