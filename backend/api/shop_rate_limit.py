"""Per-signed-customer write budgets for Telegram Mini App.

A second line of defence in front of database writes and Telegram sends.
Nginx limits source IP; this layer limits the *verified Telegram identity*,
including when many IPs are used. Redis gives consistent counters across API
workers. If it fails, small bounded local counters remain as a fallback.
This is deliberately not an anti-fraud/checkout authorization mechanism:
all domain checks and order idempotency stay in the service layer.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict

from api.webapp_auth import InitDataError, parse_init_data
from shop.config import settings
from shop.security_log import record

log = logging.getLogger(__name__)

# Requests/minute by action. Checkout is protected independently of cart taps
# and carrier suggestions; reducing those budgets must not lock out checkout.
BUDGETS = {"checkout": 8, "chat": 30, "cart": 120, "directory": 100,
           "quote": 90, "misc": 60}
WINDOW_SECONDS = 60
LOCAL_MAX_KEYS = 12000
_local: OrderedDict[tuple[str, int], int] = OrderedDict()
_logged_rejections: OrderedDict[tuple[str, int], None] = OrderedDict()
_redis_clients: dict[asyncio.AbstractEventLoop, object] = {}
_redis_fail_until = 0.0


def action_group(path: str, method: str) -> str | None:
    """Only write requests; diagnostic telemetry and visits have nginx rules."""
    if method not in ("POST", "PUT", "PATCH", "DELETE") or not path.startswith("/api/shop/"):
        return None
    if path in ("/api/shop/client-log", "/api/shop/analytics/visit"):
        return None
    if path == "/api/shop/checkout":
        return "checkout"
    if path == "/api/shop/checkout/quote":
        return "quote"
    if path.startswith("/api/shop/support/") or "/chat" in path:
        return "chat"
    if path.startswith("/api/shop/cart"):
        return "cart"
    if path.startswith("/api/shop/delivery/"):
        return "directory"
    return "misc"


def _identity_key(tg_id: int, group: str) -> str:
    # Stable across workers, does not put the Telegram ID or bearer string in Redis.
    salt = hashlib.sha256(settings.bot_token.encode()).digest()
    pseudonym = hashlib.blake2s(str(tg_id).encode(), key=salt, digest_size=12).hexdigest()
    return f"elfar:miniapp:write:{group}:{pseudonym}"


def _local_allow(key: str, max_count: int, now: float) -> bool:
    bucket = int(now // WINDOW_SECONDS)
    index = (key, bucket)
    counter = _local.get(index, 0) + 1
    _local[index] = counter
    _local.move_to_end(index)
    # Bounded storage, no user IDs kept. Expire old windows in small chunks.
    while len(_local) > LOCAL_MAX_KEYS:
        _local.popitem(last=False)
    return counter <= max_count


async def _redis_allow(key: str, limit: int, now: float) -> bool | None:
    global _redis_fail_until
    if time.monotonic() < _redis_fail_until:
        return None
    from shop.services.realtime import _redis_url
    redis_url = _redis_url()
    if not redis_url:
        return None
    try:
        import redis.asyncio as redis
        loop = asyncio.get_running_loop()
        client = _redis_clients.get(loop)
        if client is None:
            client = redis.from_url(redis_url, socket_connect_timeout=0.4,
                                    socket_timeout=0.4, health_check_interval=30)
            _redis_clients[loop] = client
        # A new key each minute; INCR + EXPIRE in a transaction prevents
        # races between uvicorn workers and bounds retention in Redis.
        bucket_key = f"{key}:{int(now // WINDOW_SECONDS)}"
        transaction = client.pipeline(transaction=True)
        transaction.incr(bucket_key)
        transaction.expire(bucket_key, WINDOW_SECONDS * 2)
        count, _ = await transaction.execute()
        return int(count) <= limit
    except Exception as exc:
        _redis_fail_until = time.monotonic() + 15
        log.warning("Mini App rate-limit Redis unavailable; local fallback: %s", type(exc).__name__)
        return None


async def allow_write(tg_id: int, group: str, *, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    key = _identity_key(tg_id, group)
    limit = BUDGETS[group]
    remote = await _redis_allow(key, limit, current)
    if remote is not None:
        return remote
    return _local_allow(key, limit, current)


async def check_signed_write(path: str, method: str, header: str) -> bool:
    """The route itself authenticates invalid/missing credentials with a 401."""
    group = action_group(path, method)
    if not group or not header:
        return True
    try:
        parsed = parse_init_data(header, settings.bot_token)
        tg_id = parsed["user"]["id"]
    except (InitDataError, KeyError, TypeError):
        return True
    if await allow_write(tg_id, group):
        return True
    # A throttled abusive client can send hundreds of 429 requests per second.
    # Log only the first rejection for that identity/action/minute, otherwise
    # the security logger itself becomes the disk/notification DoS target.
    reject_key = (_identity_key(tg_id, group), int(time.time() // WINDOW_SECONDS))
    if reject_key not in _logged_rejections:
        _logged_rejections[reject_key] = None
        if len(_logged_rejections) > LOCAL_MAX_KEYS:
            _logged_rejections.popitem(last=False)
        record("security.miniapp.rate_limited", action=group)
    return False


async def close_rate_limit_connections() -> None:
    global _redis_fail_until
    clients = list(_redis_clients.values())
    _redis_clients.clear()
    _redis_fail_until = 0.0
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass
