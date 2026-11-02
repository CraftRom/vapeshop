"""Strict Cloudflare v4 transport. Only reads get a bounded retry."""
import asyncio
import hashlib
import time
from weakref import WeakKeyDictionary
from datetime import datetime, timezone
import httpx

from shop.http_utils import retry_after_seconds

API = 'https://api.cloudflare.com/client/v4'
_cooldowns = WeakKeyDictionary()


class CloudflareError(RuntimeError):
    def __init__(self, message, status=502, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


async def request(token, method, path, *, params=None, body=None):
    method = method.upper()
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    cooldowns = _cooldowns.setdefault(asyncio.get_running_loop(), {})
    scope = hashlib.sha256(token.encode()).hexdigest()
    remaining = cooldowns.get(scope, 0) - time.monotonic()
    if remaining > 0:
        raise CloudflareError('Cloudflare: триває пауза після обмеження частоти запитів', 503, remaining)
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0), follow_redirects=False) as client:
        for attempt in range(2 if method == 'GET' else 1):
            try:
                response = await client.request(method, API + path, params=params, json=body, headers=headers)
            except httpx.RequestError as exc:
                if method == 'GET' and attempt == 0:
                    await asyncio.sleep(.25)
                    continue
                raise CloudflareError(f'Cloudflare API недоступний: {type(exc).__name__}', 503) from None
            if response.status_code in {502, 503, 504} and method == 'GET' and attempt == 0:
                delay = retry_after_seconds(response.headers.get('Retry-After'), default=.25)
                if delay > 1:
                    cooldowns[scope] = time.monotonic() + delay
                    raise CloudflareError('Cloudflare просить зачекати перед наступним запитом', 503, delay)
                await asyncio.sleep(max(.25, delay))
                continue
            if response.status_code == 429:
                delay = retry_after_seconds(response.headers.get('Retry-After'), default=60)
                cooldowns[scope] = time.monotonic() + delay
                raise CloudflareError('Cloudflare обмежив частоту запитів. Дочекайтеся завершення паузи', 503, delay)
            try:
                data = response.json()
            except ValueError:
                raise CloudflareError('Cloudflare повернув нечитабельну JSON-відповідь') from None
            if not isinstance(data, dict):
                raise CloudflareError('Cloudflare повернув некоректну структуру відповіді')
            if response.status_code >= 300 or data.get('success') is not True:
                errors = data.get('errors')
                errors = errors if isinstance(errors, list) else []
                messages = [str(item.get('message') or '') if isinstance(item, dict) else str(item) for item in errors[:3]]
                message = '; '.join(filter(None, messages)) or f'Cloudflare HTTP {response.status_code}: запит не підтверджено'
                # Provider text can echo credentials supplied to a malformed request.
                message = message.replace(token, '[redacted]') if token else message
                raise CloudflareError(message[:500], 502 if response.status_code >= 500 else 400)
            return data


async def verify_token(token, account_id=''):
    path = f'/accounts/{account_id}/tokens/verify' if account_id else '/user/tokens/verify'
    data = await request(token, 'GET', path)
    result = data.get('result')
    if not isinstance(result, dict) or result.get('status') != 'active':
        raise CloudflareError('Cloudflare: токен не активний або відповідь перевірки некоректна', 400)
    for field, expired in [('expires_on', True), ('not_before', False)]:
        value = result.get(field)
        if not value:
            continue
        try:
            moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        except ValueError:
            raise CloudflareError('Cloudflare повернув некоректний термін дії токена', 502) from None
        now = datetime.now(timezone.utc)
        if (expired and moment <= now) or (not expired and moment > now):
            raise CloudflareError('Cloudflare: термін дії токена завершився або ще не почався', 400)
    return result
