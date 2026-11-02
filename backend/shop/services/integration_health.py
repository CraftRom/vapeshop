"""Read-only probes. Never create orders, shipments, DNS records or send messages."""
import asyncio
from datetime import datetime, timezone
import time

import httpx
from shop.config import settings
from shop.secret_crypto import decrypt_secret
from shop.services.shop_settings import get_shop_settings


async def inspect_integrations(repo, *, live=False):
    shop = await get_shop_settings(repo)
    raw = await repo.get_settings_map()
    try:
        cf_token = decrypt_secret(raw.get('promo_cloudflare_api_token') or '') if raw.get('promo_cloudflare_api_token') else ''
    except Exception:
        cf_token = ''
    account = raw.get('promo_cloudflare_account_id') or ''
    secrets = [settings.bot_token, shop.novaposhta_api_key, shop.salesdrive_api_key, cf_token]

    async def telegram():
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(f'https://api.telegram.org/bot{settings.bot_token}/getMe')
        data = response.json()
        if response.status_code != 200 or not isinstance(data, dict) or data.get('ok') is not True or not isinstance(data.get('result'), dict):
            raise RuntimeError('Telegram не підтвердив ключ бота')
        return 'Ключ бота перевірено методом getMe; повідомлень не надсилали'

    async def nova():
        from shop.services import novaposhta
        await novaposhta._call(shop.novaposhta_api_key, 'Address', 'searchSettlements', {'CityName':'Київ', 'Limit':'1', 'Page':'1'})
        return 'Ключ і читання довідника перевірено; накладних не створювали'

    async def salesdrive():
        from shop.services import salesdrive
        await salesdrive.status_options(shop, force=True)
        return 'Ключ і читання статусів перевірено; заявки не змінювали'

    async def cloudflare():
        from shop.services.cloudflare import verify_token
        await verify_token(cf_token, account)
        return 'Активність токена перевірено; DNS і SSL не змінювали'

    async def probe(name, configured, action):
        if not configured:
            return {'provider':name, 'state':'not_configured', 'message':'Потрібні налаштування доступу', 'latencyMs':None}
        if not live:
            return {'provider':name, 'state':'configured', 'message':'Налаштовано. Для мережевої перевірки запустіть live-режим', 'latencyMs':None}
        started = time.monotonic()
        try:
            message = await asyncio.wait_for(action(), timeout=12)
            state = 'ok'
        except Exception as exc:
            state = 'error'
            message = str(exc) or type(exc).__name__
            for secret in secrets:
                if secret:
                    message = message.replace(secret, '[redacted]')
            message = message[:300]
        return {'provider':name, 'state':state, 'message':message, 'latencyMs':round((time.monotonic()-started)*1000)}

    rows = await asyncio.gather(
        probe('telegram', bool(settings.bot_token), telegram),
        probe('novaposhta', bool(shop.novaposhta_api_key), nova),
        probe('salesdrive', bool(shop.salesdrive_domain and shop.salesdrive_api_key), salesdrive),
        probe('cloudflare', bool(cf_token), cloudflare),
    )
    rows += [
        {'provider':'google_tags', 'state':'client_side', 'message':'Google tag, GTM та Consent Mode перевіряються на опублікованій сторінці; доступ до звітів GA4/Ads цим кодом не перевіряється', 'latencyMs':None},
        {'provider':'acme', 'state':'runtime_required', 'message':'ACME v2 / Let’s Encrypt перевіряється Certbot на VPS; сертифікати не випускаються під час цієї перевірки', 'latencyMs':None},
        {'provider':'dns_origin', 'state':'runtime_required', 'message':'Публічний IP і DNS-over-HTTPS перевіряє promo-controller на VPS', 'latencyMs':None},
    ]
    errors = sum(row['state']=='error' for row in rows)
    verified = sum(row['state']=='ok' for row in rows)
    return {'checkedAt':datetime.now(timezone.utc).isoformat(), 'live':live,
            'status':'error' if errors else 'partial', 'verified':verified, 'errors':errors,
            'readOnly':True, 'providers':rows}
