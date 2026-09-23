"""Autonomous SalesDrive read-side reconciliation.

Webhook is the primary zero-wait path for CRM -> ELFAR. This worker is the
self-healing path when a webhook is lost, misconfigured or the dedicated
scheduler container is temporarily unavailable.

The API process and scheduler may both call :func:`refresh_once`; a Redis
lease shared by the already configured Redis instance guarantees that only
one of them performs a SalesDrive ``/api/order/list/`` batch in a refresh
window. No new environment variable is required.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from shop.config import settings
from shop.repo.factory import open_repo
from shop.services.shop_settings import get_shop_settings

log = logging.getLogger(__name__)

# SalesDrive order-list quota is 10/min, 100/hour and 1000/day. One shared
# batch per 120 seconds is at most 720 requests/day before natural no-candidate
# skips, leaving headroom for manual refreshes and diagnostics.
ACTIVE_REFRESH_SECONDS = 120
TERMINAL_REFRESH_SECONDS = 6 * 3600
LEASE_SECONDS = ACTIVE_REFRESH_SECONDS
LEASE_KEY = "elfar:salesdrive:reconcile:v2"


def _redis_url() -> str:
    configured = str(getattr(settings, "redis_url", "") or "").strip()
    if configured:
        return configured
    password = str(getattr(settings, "redis_password", "") or "").strip()
    if password and not getattr(settings, "serverless", False):
        return f"redis://:{quote(password, safe='')}@redis:6379/0"
    return ""


async def _claim_lease() -> tuple[object | None, str, str | None]:
    """Try to reserve one cross-process refresh window.

    Returns ``(client, token, reason)``. The lease is deliberately not deleted
    after success: its TTL is the shared cadence gate, so API and scheduler
    cannot immediately run the same external read one after another.
    """
    url = _redis_url()
    if not url:
        return None, "", "redis_unconfigured"

    try:
        import redis.asyncio as redis

        client = redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.8,
            health_check_interval=30,
        )
        token = uuid.uuid4().hex
        claimed = await client.set(LEASE_KEY, token, nx=True, ex=LEASE_SECONDS)
        if not claimed:
            await client.aclose()
            return None, "", "lease_busy"
        return client, token, None
    except Exception as exc:
        log.warning(
            "Redis lease для SalesDrive reconcile недоступний: %s",
            exc,
            extra={"event": "salesdrive.reconcile.lease_failed"},
        )
        try:
            await client.aclose()  # type: ignore[name-defined]
        except Exception:
            pass
        return None, "", "redis_unavailable"


async def refresh_once(*, allow_without_redis: bool = False, source: str = "unknown") -> dict:
    """Refresh one fair batch of stale CRM-linked orders.

    ``allow_without_redis`` is true only for the dedicated scheduler. This is
    intentional: if Redis itself is down, the scheduler stays the single
    fallback writer, while the embedded API watchdog backs off instead of
    doubling SalesDrive traffic.
    """
    from shop.services import salesdrive

    client, _token, lease_reason = await _claim_lease()
    if lease_reason == "lease_busy":
        return {"checked": 0, "refreshed": 0, "failed": 0, "deferred": 0,
                "skipped": "lease_busy", "source": source}
    if lease_reason and not allow_without_redis:
        return {"checked": 0, "refreshed": 0, "failed": 0, "deferred": 0,
                "skipped": lease_reason, "source": source}

    try:
        batch = max(1, min(int(settings.salesdrive_background_batch), 100))
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=ACTIVE_REFRESH_SECONDS)
        terminal_stale_before = now - timedelta(seconds=TERMINAL_REFRESH_SECONDS)

        async with open_repo() as repo:
            shop = await get_shop_settings(repo)
            if not shop.salesdrive_api_connected:
                return {"checked": 0, "refreshed": 0, "failed": 0,
                        "deferred": 0, "skipped": "api_disconnected", "source": source}

            candidates = await repo.list_crm_refresh_candidates(
                stale_before=stale_before,
                terminal_stale_before=terminal_stale_before,
                limit=batch,
            )
            order_ids = [order.id for order in candidates]
            if not order_ids:
                return {"checked": 0, "refreshed": 0, "failed": 0,
                        "deferred": 0, "source": source}

            result = await salesdrive.pull_orders_batch(repo, order_ids, shop=shop, bot=None)
            result = dict(result or {})
            result["source"] = source
            return result
    finally:
        # Do not DEL the lease: TTL is the cross-process rate gate. We only
        # close the client connection. If Redis was unavailable, client=None.
        if client is not None:
            try:
                await client.aclose()  # type: ignore[attr-defined]
            except Exception:
                pass


async def api_watchdog_loop(stop_event) -> None:
    """API-side safety net for deployments where scheduler is unhealthy.

    It wakes frequently but external reads remain bounded by the shared Redis
    lease. This makes status freshness independent of opening an order card.
    """
    import asyncio

    # Give API startup a few seconds before the first background read.
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=5)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            result = await refresh_once(allow_without_redis=False, source="api-watchdog")
            if result.get("failed"):
                log.warning(
                    "API watchdog SalesDrive: checked=%s refreshed=%s failed=%s deferred=%s",
                    result.get("checked", 0), result.get("refreshed", 0),
                    result.get("failed", 0), result.get("deferred", 0),
                    extra={"event": "salesdrive.reconcile.watchdog", **result},
                )
            elif result.get("refreshed"):
                log.info(
                    "API watchdog SalesDrive: checked=%s refreshed=%s",
                    result.get("checked", 0), result.get("refreshed", 0),
                    extra={"event": "salesdrive.reconcile.watchdog", **result},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Помилка API watchdog SalesDrive")

        # Short wake-up is cheap; Redis lease + stale timestamps decide if an
        # external request is actually needed.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass
