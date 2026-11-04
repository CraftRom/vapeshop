"""Deterministic budget tests without production Redis or DB."""
import asyncio
import json
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

os.environ.setdefault('BOT_TOKEN', '777001:TESTTOKEN')
from api import shop_rate_limit as budget
from shop.config import settings

passed = 0

def check(condition, description):
    global passed
    if not condition:
        raise AssertionError(description)
    passed += 1
    print('✓', description)


def signed(user_id):
    pairs = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': user_id})}
    data = '\n'.join(f'{k}={pairs[k]}' for k in sorted(pairs))
    secret = hmac.new(b'WebAppData', settings.bot_token.encode(), hashlib.sha256).digest()
    return urlencode({**pairs, 'hash': hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()})


async def main():
    async def no_redis(key, limit, now):
        return None
    budget._redis_allow = no_redis
    check(budget.action_group('/api/shop/checkout', 'POST') == 'checkout', 'checkout has separate budget')
    check(budget.action_group('/api/shop/checkout/quote', 'POST') == 'quote', 'quote does not exhaust checkout budget')
    check(budget.action_group('/api/shop/orders/17/chat', 'POST') == 'chat', 'order chat budget')
    check(budget.action_group('/api/shop/support/threads/9/messages', 'POST') == 'chat', 'support and chat share budget')
    check(budget.action_group('/api/shop/cart', 'DELETE') == 'cart', 'cart removal has a budget')
    check(budget.action_group('/api/shop/client-log', 'POST') is None, 'telemetry keeps independent Nginx throttle')
    check(budget.action_group('/api/auth/login', 'POST') is None, 'dashboard remains unaffected')
    check(budget.action_group('/api/shop/orders', 'GET') is None, 'read-only requests unaffected')
    budget._local.clear()
    token = signed(7331)
    for _ in range(8):
        check(await budget.check_signed_write('/api/shop/checkout', 'POST', token), 'checkout accepted below budget')
    check(not await budget.check_signed_write('/api/shop/checkout', 'POST', token), 'same identity blocked at ninth checkout')
    check(await budget.check_signed_write('/api/shop/checkout', 'POST', signed(7332)), 'another customer unaffected')
    check(await budget.check_signed_write('/api/shop/checkout/quote', 'POST', token), 'different write class unaffected')
    check(await budget.check_signed_write('/api/shop/checkout', 'POST', 'invalid'), 'invalid signatures delegated to auth 401')
    check(budget._identity_key(7331, 'checkout') != budget._identity_key(7332, 'checkout'), 'per-user isolation')
    check('7331' not in budget._identity_key(7331, 'checkout'), 'Telegram ID not exposed in rate key')
    budget._local.clear()
    check(budget._local_allow('window', 1, 600.5), 'first request in window accepted')
    check(not budget._local_allow('window', 1, 601.5), 'second request in window blocked')
    check(budget._local_allow('window', 1, 660.5), 'new minute resets budget')

    # Actual ASGI wire: middleware must return 429 (including Retry-After)
    # before the route runs, without reading an upload or touching a DB.
    import httpx
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route
    from api.security_middleware import SecurityMiddleware
    calls = []
    async def handler(request):
        calls.append(True)
        return Response(status_code=204)
    app = Starlette(routes=[Route('/api/shop/checkout', handler, methods=['POST'])])
    app.add_middleware(SecurityMiddleware)
    budget._local.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://testserver') as client:
        for _ in range(8):
            resp = await client.post('/api/shop/checkout',
                                     headers={'X-Telegram-Init-Data': token}, json={})
            check(resp.status_code == 204, 'signed checkout passes middleware under limit')
        resp = await client.post('/api/shop/checkout',
                                 headers={'X-Telegram-Init-Data': token}, json={})
        check(resp.status_code == 429 and resp.headers.get('retry-after') == '60',
              'ASGI returns 429 with retry-after on over-budget write')
        check(len(calls) == 8, 'rejected mutation never reaches business handler')
        resp = await client.post('/api/shop/checkout',
                                 headers={'X-Telegram-Init-Data': signed(7332)}, json={})
        check(resp.status_code == 204, 'another customer can still check out')
    print(f'Mini App write budgets: {passed}/{passed}')

asyncio.run(main())
