from __future__ import annotations

import html
import json
import os
import re
import hashlib
import base64
import secrets

import httpx
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import Principal, require_staff
from shop import security_log as security
from shop.db import get_session
from shop.secret_crypto import encrypt_secret, decrypt_secret
from shop.models import PromoLandingDailyStat, PromoLandingPage, Setting

router = APIRouter()

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_BOT_RE = re.compile(r"bot|crawler|spider|slurp|facebookexternalhit|preview|monitor|uptime", re.I)

_PROMO_CONTROLLER_URL = os.environ.get("PROMO_CONTROLLER_URL", "http://promo-controller:8787").rstrip("/")
_PROMO_CONTROLLER_TOKEN = os.environ.get("PROMO_CONTROLLER_TOKEN", "").strip()


async def _controller(method: str, path: str, *, domain: str, extra: dict | None = None) -> dict:
    if not _PROMO_CONTROLLER_TOKEN:
        raise HTTPException(503, "Контролер промо-доменів не налаштований")
    headers = {"Authorization": f"Bearer {_PROMO_CONTROLLER_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(190.0, connect=5.0)) as client:
            if method == "GET":
                response = await client.get(f"{_PROMO_CONTROLLER_URL}{path}", params={"domain": domain}, headers=headers)
            else:
                response = await client.request(method, f"{_PROMO_CONTROLLER_URL}{path}", json={"domain": domain, **(extra or {})}, headers=headers)
    except httpx.RequestError:
        raise HTTPException(503, "Ізольований контролер доменів недоступний")
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400:
        raise HTTPException(response.status_code if response.status_code < 500 else 503, payload.get("detail") or "Помилка контролера доменів")
    return payload


async def _domain_status(domain: str) -> dict:
    return await _controller("GET", "/v1/status", domain=domain)


CF_TOKEN_KEY = "promo_cloudflare_api_token"
CF_API = "https://api.cloudflare.com/client/v4"


async def _cf_token(db: AsyncSession) -> str:
    row = await db.get(Setting, CF_TOKEN_KEY)
    if not row or not (row.value or "").strip():
        return ""
    try:
        return decrypt_secret(row.value).strip()
    except Exception:
        return ""


async def _cf_request(token: str, method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            r = await client.request(method, f"{CF_API}{path}", params=params, json=body, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Cloudflare API недоступний: {type(exc).__name__}")
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code >= 400 or data.get("success") is False:
        errors = data.get("errors") or []
        msg = "; ".join(str(x.get("message") or x) for x in errors[:3]) or f"Cloudflare HTTP {r.status_code}"
        raise HTTPException(502 if r.status_code >= 500 else 400, msg)
    return data


async def _cf_find_zone(token: str, domain: str) -> dict | None:
    labels = domain.split('.')
    # Cloudflare zones are normally an apex domain; walk upward and pick first exact active zone.
    for i in range(0, max(1, len(labels)-1)):
        candidate = '.'.join(labels[i:])
        if candidate.count('.') < 1:
            break
        data = await _cf_request(token, 'GET', '/zones', params={'name': candidate, 'status': 'active', 'per_page': 5})
        rows = data.get('result') or []
        if rows:
            return rows[0]
    return None


async def _cloudflare_domain_info(db: AsyncSession, domain: str, origin_ipv4: str | None = None) -> dict:
    token = await _cf_token(db)
    if not token:
        return {"configured": False, "connected": False, "detected": False}
    try:
        zone = await _cf_find_zone(token, domain)
        if not zone:
            return {"configured": True, "connected": True, "detected": False, "error": "Домен не знайдено серед доступних Cloudflare zones"}
        zid = zone.get('id')
        dns = await _cf_request(token, 'GET', f'/zones/{zid}/dns_records', params={'name': domain, 'per_page': 100})
        records = []
        for r in dns.get('result') or []:
            if r.get('type') not in {'A','AAAA','CNAME'}:
                continue
            records.append({
                'id': r.get('id'), 'type': r.get('type'), 'name': r.get('name'),
                'content': r.get('content'), 'proxied': bool(r.get('proxied')),
                'proxiable': bool(r.get('proxiable')), 'ttl': r.get('ttl'),
            })
        try:
            ssl_data = await _cf_request(token, 'GET', f'/zones/{zid}/settings/ssl')
            ssl_mode = (ssl_data.get('result') or {}).get('value')
        except HTTPException:
            ssl_mode = None
        proxied = any(r['proxied'] for r in records if r['type'] in {'A','AAAA','CNAME'})
        a_records = [r for r in records if r['type'] == 'A']
        origin_matches = bool(origin_ipv4) and any(r['content'] == origin_ipv4 for r in a_records)
        ready = bool(proxied and origin_matches)
        return {
            'configured': True, 'connected': True, 'detected': True,
            'zone': {'id': zid, 'name': zone.get('name'), 'status': zone.get('status')},
            'records': records, 'proxied': proxied, 'originIpv4': origin_ipv4,
            'originMatches': origin_matches, 'sslMode': ssl_mode,
            'strict': ssl_mode == 'strict', 'readyForProxyDeploy': ready,
        }
    except HTTPException as exc:
        return {"configured": True, "connected": False, "detected": False, "error": str(exc.detail)}



async def _public_site_probe(domain: str) -> dict:
    url = f"https://{domain}/"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "elfar-promo-check/1.0"})
        code = response.status_code
        if 200 <= code < 400:
            return {"ok": True, "status": "up", "code": code, "label": "Працює", "message": "Сайт відкривається для відвідувачів."}
        if code in {401, 403}:
            return {"ok": False, "status": "blocked", "code": code, "label": "Обмежено", "message": "Сайт відповідає, але доступ зараз обмежений."}
        if 400 <= code < 500:
            return {"ok": False, "status": "error", "code": code, "label": "Є проблема", "message": f"Сайт відповідає помилкою {code}."}
        return {"ok": False, "status": "error", "code": code, "label": "Є проблема", "message": f"Сайт відповідає помилкою {code}."}
    except httpx.ConnectError:
        return {"ok": False, "status": "down", "label": "Недоступний", "message": "Не вдалося підключитися до сайту."}
    except httpx.ConnectTimeout:
        return {"ok": False, "status": "slow", "label": "Немає відповіді", "message": "Сайт не встиг відповісти вчасно."}
    except httpx.ReadTimeout:
        return {"ok": False, "status": "slow", "label": "Повільна відповідь", "message": "Сайт відповідає занадто повільно."}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "error", "label": "Помилка перевірки", "message": f"Не вдалося перевірити сайт: {type(exc).__name__}."}


DEFAULT_CONTENT = {
    "background_image": "",
    "logo_image": "",
    "eyebrow": "",
    "title": "Телеграм канал шалених знижок 🔥",
    "promo_label": "Ваш персональний промокод:",
    "promo_code": "PROMO2026",
    "description": "Отримайте 7% знижки, скориставшись ним під час замовлення.",
    "validity_text": "Не зволікайте — промокод активний лише 1 добу після отримання.",
    "button_text": "ПЕРЕЙТИ",
    "button_url": "https://t.me/",
    "footer_text": "",
}

DEFAULT_SEO = {
    "title": "Акційна пропозиція",
    "description": "Отримайте персональний промокод та скористайтеся спеціальною пропозицією.",
    "keywords": "",
    "canonical_url": "",
    "robots": "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1",
    "og_title": "",
    "og_description": "",
    "og_image": "",
    "og_locale": "uk_UA",
    "site_name": "",
    "schema_name": "",
    "schema_description": "",
}

DEFAULT_GOOGLE = {
    "enabled": False,
    "mode": "google_tag",
    "google_tag_id": "",
    "gtm_container_id": "",
    "ads_conversion_id": "",
    "ads_conversion_label": "",
    "search_console_verification": "",
    "consent_mode": "banner",
}


def _domain(value: str) -> str:
    value = (value or "").strip().lower().rstrip(".")
    if value.startswith("http://") or value.startswith("https://"):
        value = (urlparse(value).hostname or "").lower()
    if not _DOMAIN_RE.fullmatch(value):
        raise ValueError("Вкажіть домен без шляху, наприклад promo.example.com")
    return value


def _local_image(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value
    if not path.startswith("/media/") or ".." in path or "\\" in path:
        raise ValueError("Зображення промо-сторінки мають бути завантажені у локальне сховище /media/")
    return path


def _url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Посилання має починатися з https:// або http://")
    return value


_GOOGLE_TAG_RE = re.compile(r"^(?:G-[A-Z0-9]+|GT-[A-Z0-9]+|AW-[0-9]+)$", re.I)
_GTM_RE = re.compile(r"^GTM-[A-Z0-9]+$", re.I)
_ADS_ID_RE = re.compile(r"^AW-[0-9]+$", re.I)
_ADS_LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_VERIFY_RE = re.compile(r"^[A-Za-z0-9_=-]{6,200}$")


def _google_id(value: str, pattern: re.Pattern, label: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not pattern.fullmatch(value):
        raise ValueError(f"Некоректний {label}")
    return value.upper()


class GoogleIn(BaseModel):
    enabled: bool = False
    mode: str = "google_tag"
    google_tag_id: str = ""
    gtm_container_id: str = ""
    ads_conversion_id: str = ""
    ads_conversion_label: str = ""
    search_console_verification: str = ""
    consent_mode: str = "banner"

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str) -> str:
        if value not in {"google_tag", "gtm"}:
            raise ValueError("Режим Google має бути google_tag або gtm")
        return value

    @field_validator("consent_mode")
    @classmethod
    def valid_consent_mode(cls, value: str) -> str:
        if value not in {"banner", "granted", "disabled"}:
            raise ValueError("Некоректний режим згоди")
        return value

    @field_validator("google_tag_id")
    @classmethod
    def valid_google_tag(cls, value: str) -> str:
        return _google_id(value, _GOOGLE_TAG_RE, "Google tag ID")

    @field_validator("gtm_container_id")
    @classmethod
    def valid_gtm(cls, value: str) -> str:
        return _google_id(value, _GTM_RE, "GTM container ID")

    @field_validator("ads_conversion_id")
    @classmethod
    def valid_ads_id(cls, value: str) -> str:
        return _google_id(value, _ADS_ID_RE, "Google Ads conversion ID")

    @field_validator("ads_conversion_label")
    @classmethod
    def valid_ads_label(cls, value: str) -> str:
        value = (value or "").strip()
        if value and not _ADS_LABEL_RE.fullmatch(value):
            raise ValueError("Некоректний Google Ads conversion label")
        return value

    @field_validator("search_console_verification")
    @classmethod
    def valid_verification(cls, value: str) -> str:
        value = (value or "").strip()
        if value and not _VERIFY_RE.fullmatch(value):
            raise ValueError("Некоректний токен Google Search Console")
        return value


class ContentIn(BaseModel):
    background_image: str = ""
    logo_image: str = ""
    eyebrow: str = Field("", max_length=120)
    title: str = Field("", max_length=180)
    promo_label: str = Field("", max_length=160)
    promo_code: str = Field("", max_length=64)
    description: str = Field("", max_length=700)
    validity_text: str = Field("", max_length=500)
    button_text: str = Field("", max_length=80)
    button_url: str = ""
    footer_text: str = Field("", max_length=500)

    @field_validator("background_image", "logo_image")
    @classmethod
    def local_image(cls, value: str) -> str:
        return _local_image(value)

    @field_validator("button_url")
    @classmethod
    def valid_button_url(cls, value: str) -> str:
        return _url(value)


class SeoIn(BaseModel):
    title: str = Field("", max_length=70)
    description: str = Field("", max_length=180)
    keywords: str = Field("", max_length=500)
    canonical_url: str = ""
    robots: str = Field(DEFAULT_SEO["robots"], max_length=160)
    og_title: str = Field("", max_length=100)
    og_description: str = Field("", max_length=200)
    og_image: str = ""
    og_locale: str = Field("uk_UA", max_length=16)
    site_name: str = Field("", max_length=100)
    schema_name: str = Field("", max_length=120)
    schema_description: str = Field("", max_length=240)

    @field_validator("canonical_url")
    @classmethod
    def canonical(cls, value: str) -> str:
        return _url(value)

    @field_validator("og_image")
    @classmethod
    def local_og_image(cls, value: str) -> str:
        return _local_image(value)


class LandingPageIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    domain: str
    content: ContentIn = Field(default_factory=lambda: ContentIn(**DEFAULT_CONTENT))
    seo: SeoIn = Field(default_factory=lambda: SeoIn(**DEFAULT_SEO))
    google: GoogleIn = Field(default_factory=lambda: GoogleIn(**DEFAULT_GOOGLE))

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        return _domain(value)




_SEO_STOPWORDS = {
    "і", "й", "та", "або", "в", "у", "на", "до", "для", "з", "зі", "із", "по", "про", "під",
    "це", "цей", "ця", "ці", "ваш", "ваша", "ваші", "наш", "наша", "отримайте", "скористайтеся",
    "не", "лише", "після", "під час", "перейти", "промокод", "акція", "акційна", "пропозиція",
}

def _clean_text(value: str) -> str:
    value = re.sub(r"[\s\u00a0]+", " ", (value or "")).strip()
    return re.sub(r"[<>]", "", value)

def _clip(value: str, limit: int) -> str:
    value = _clean_text(value)
    if len(value) <= limit:
        return value
    cut = value[: limit + 1]
    cut = cut.rsplit(" ", 1)[0] or value[:limit]
    return cut.rstrip(" ,.;:!?—-")

def _brand_from_domain(domain: str, name: str) -> str:
    host = (domain or "").split(".")[0].replace("-", " ").replace("_", " ").strip()
    generic = {"promo", "sale", "offer", "go", "landing", "www"}
    if host and host.lower() not in generic and len(host) >= 3:
        return host.title()
    cleaned = re.sub(r"\b(промо|promo|landing|сторінка|акція|акційна)\b", " ", name or "", flags=re.I)
    cleaned = _clean_text(cleaned)
    return _clip(cleaned, 42) or "ELFAR"

def _offer_signal(content: dict) -> str:
    source = " ".join(str(content.get(k) or "") for k in ("title", "description", "validity_text", "promo_code"))
    percent = re.search(r"(?<!\d)(\d{1,2})\s*%", source)
    money = re.search(r"(?<!\d)(\d{2,5})\s*(?:грн|₴)", source, re.I)
    if percent:
        return f"знижка {percent.group(1)}%"
    if money:
        return f"вигода {money.group(1)} грн"
    if content.get("promo_code"):
        return "промокод на спеціальну пропозицію"
    return "спеціальна пропозиція"

def _keywords(content: dict, brand: str, signal: str, domain: str) -> str:
    text = " ".join(_clean_text(str(content.get(k) or "")).lower() for k in ("title", "description", "validity_text", "eyebrow"))
    words = re.findall(r"[a-zа-яіїєґ0-9-]{3,}", text, flags=re.I)
    ranked, seen = [], set()
    for word in words:
        key = word.lower()
        if key in _SEO_STOPWORDS or key in seen or key.isdigit():
            continue
        seen.add(key); ranked.append(key)
        if len(ranked) >= 7:
            break
    base = [brand.lower(), signal.lower(), "промокод", "знижка", domain.lower()] + ranked
    out=[]; seen=set()
    for item in base:
        item=_clean_text(item)
        if item and item not in seen:
            seen.add(item); out.append(item)
    return ", ".join(out[:10])

def _pick(options: list[str], seed: str, salt: str) -> str:
    digest = hashlib.blake2b(f"{seed}|{salt}".encode("utf-8"), digest_size=8).digest()
    return options[int.from_bytes(digest, "big") % len(options)]

def generate_seo_payload(*, name: str, domain: str, content: dict, variant_seed: str = "") -> dict:
    """Generate production-safe SEO copy from the actual promo content.

    It is intentionally rule-based and deterministic for a given seed: this makes output
    explainable/reproducible while still avoiding one static template for every page.
    """
    brand = _brand_from_domain(domain, name)
    signal = _offer_signal(content)
    title = _clean_text(content.get("title") or name or "Спеціальна пропозиція")
    desc = _clean_text(content.get("description") or "")
    validity = _clean_text(content.get("validity_text") or "")
    code = _clean_text(content.get("promo_code") or "")
    seed = variant_seed or f"{domain}|{name}|{title}|{desc}|{code}"

    title_variants = [
        f"{title} — {brand}",
        f"{signal.capitalize()} від {brand} | {title}",
        f"{brand}: {title}",
        f"{title} | {signal.capitalize()}",
    ]
    meta_title = _clip(_pick(title_variants, seed, "title"), 68)

    desc_bits = [x for x in (desc, validity) if x]
    joined = " ".join(desc_bits) or f"Скористайтеся пропозицією {brand} та отримайте {signal}."
    description_variants = [
        joined,
        f"{signal.capitalize()} від {brand}. {joined}",
        f"Дізнайтеся умови пропозиції {brand}. {joined}",
        f"Отримайте {signal} від {brand}. {joined}",
    ]
    meta_description = _clip(_pick(description_variants, seed, "description"), 170)

    og_title_variants = [meta_title, _clip(f"{title} — {signal}", 96), _clip(f"{brand} · {title}", 96)]
    og_desc_variants = [meta_description, _clip(joined, 195), _clip(f"{signal.capitalize()}. {joined}", 195)]
    schema_name = _clip(_pick([title, meta_title, f"{brand} — {signal}"], seed, "schema-name"), 118)
    schema_desc = _clip(_pick([joined, meta_description, f"{title}. {joined}"], seed, "schema-desc"), 235)

    return {
        "title": meta_title,
        "description": meta_description,
        "keywords": _clip(_keywords(content, brand, signal, domain), 490),
        "canonical_url": f"https://{domain}/",
        "robots": DEFAULT_SEO["robots"],
        "og_title": _pick(og_title_variants, seed, "og-title"),
        "og_description": _pick(og_desc_variants, seed, "og-desc"),
        "og_image": content.get("background_image") or content.get("logo_image") or "",
        "og_locale": "uk_UA",
        "site_name": _clip(brand, 96),
        "schema_name": schema_name,
        "schema_description": schema_desc,
    }

def _should_generate_initial_seo(seo: dict) -> bool:
    # UI creates a page with the stock defaults. Treat those as placeholders, not
    # deliberate SEO copy supplied by an API client.
    meaningful = {k: v for k, v in (seo or {}).items() if _clean_text(str(v or ""))}
    if not meaningful:
        return True
    return all((seo or {}).get(k, DEFAULT_SEO[k]) == DEFAULT_SEO[k] for k in DEFAULT_SEO)


def _config(data: LandingPageIn) -> dict:
    return {"content": data.content.model_dump(), "seo": data.seo.model_dump(), "google": data.google.model_dump()}


def _dto(row: PromoLandingPage) -> dict:
    draft = row.draft_config or {"content": DEFAULT_CONTENT, "seo": DEFAULT_SEO}
    return {
        "id": row.id,
        "name": row.name,
        "domain": row.domain,
        "draft": draft,
        "published": row.published_config,
        "isPublished": row.is_published,
        "version": row.version,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "publishedAt": row.published_at,
        "publicUrl": f"https://{row.domain}/",
    }


class CloudflareConfigIn(BaseModel):
    api_token: str = Field(min_length=20, max_length=256)


@router.get("/cloudflare/config")
async def cloudflare_config_status(
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    token = await _cf_token(db)
    return {"configured": bool(token)}


@router.put("/cloudflare/config")
async def cloudflare_config_save(
    data: CloudflareConfigIn,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    # Only admin roles may replace infrastructure credentials.
    if not who.is_admin:
        raise HTTPException(403, "Cloudflare API Token може змінювати лише адміністратор")
    token = data.api_token.strip()
    # Verify before storing. /user/tokens/verify works for API Tokens.
    await _cf_request(token, 'GET', '/user/tokens/verify')
    row = await db.get(Setting, CF_TOKEN_KEY)
    encrypted = encrypt_secret(token)
    if row:
        row.value = encrypted
    else:
        db.add(Setting(key=CF_TOKEN_KEY, value=encrypted))
    await db.commit()
    security.record('promo.cloudflare.configured', actor=who.login, reason='API token verified')
    return {"configured": True}


@router.delete("/cloudflare/config")
async def cloudflare_config_remove(
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    if not who.is_admin:
        raise HTTPException(403, "Cloudflare API Token може змінювати лише адміністратор")
    row = await db.get(Setting, CF_TOKEN_KEY)
    if row:
        await db.delete(row); await db.commit()
    security.record('promo.cloudflare.disconnected', actor=who.login, reason='token removed')
    return {"configured": False}


@router.get("/cloudflare/domain")
async def cloudflare_domain_status(
    domain: str,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    target = _domain(domain)
    ctrl = await _domain_status(target)
    origin = (ctrl.get('dnsRequirements') or {}).get('ipv4')
    return await _cloudflare_domain_info(db, target, origin)


@router.post("/cloudflare/domain/sync")
async def cloudflare_domain_sync(
    domain: str,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    if not who.is_admin:
        raise HTTPException(403, "DNS Cloudflare може змінювати лише адміністратор")
    target = _domain(domain)
    token = await _cf_token(db)
    if not token:
        raise HTTPException(409, "Спочатку підключіть Cloudflare API")
    ctrl = await _domain_status(target)
    origin = (ctrl.get('dnsRequirements') or {}).get('ipv4')
    if not origin:
        raise HTTPException(409, "Не вдалося визначити IPv4 VPS")
    zone = await _cf_find_zone(token, target)
    if not zone:
        raise HTTPException(404, "Cloudflare zone для домену не знайдено")
    zid = zone['id']
    dns = await _cf_request(token, 'GET', f'/zones/{zid}/dns_records', params={'name': target, 'per_page': 100})
    exact = dns.get('result') or []
    if any(r.get('type') == 'CNAME' for r in exact):
        raise HTTPException(409, "Для домену вже існує CNAME. Автоматично замінювати його на A небезпечно; приберіть конфлікт вручну.")
    arecs = [r for r in exact if r.get('type') == 'A']
    if len(arecs) > 1:
        raise HTTPException(409, "Для домену існує кілька A-записів. Автоматичне об'єднання може зламати балансування; залиште один запис вручну.")
    body = {'type': 'A', 'name': target, 'content': origin, 'ttl': 1, 'proxied': True}
    if arecs:
        await _cf_request(token, 'PATCH', f"/zones/{zid}/dns_records/{arecs[0]['id']}", body=body)
        action = 'updated'
    else:
        await _cf_request(token, 'POST', f'/zones/{zid}/dns_records', body=body)
        action = 'created'
    security.record('promo.cloudflare.dns.synced', actor=who.login, reason=f'{target}; {action}; proxied=true')
    return await _cloudflare_domain_info(db, target, origin)


@router.post("/cloudflare/domain/strict")
async def cloudflare_enable_strict(
    domain: str,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    if not who.is_admin:
        raise HTTPException(403, "SSL mode Cloudflare може змінювати лише адміністратор")
    target = _domain(domain)
    token = await _cf_token(db)
    if not token:
        raise HTTPException(409, "Спочатку підключіть Cloudflare API")
    zone = await _cf_find_zone(token, target)
    if not zone:
        raise HTTPException(404, "Cloudflare zone для домену не знайдено")
    await _cf_request(token, 'PATCH', f"/zones/{zone['id']}/settings/ssl", body={'value': 'strict'})
    security.record('promo.cloudflare.ssl.strict', actor=who.login, reason=target)
    ctrl = await _domain_status(target)
    origin = (ctrl.get('dnsRequirements') or {}).get('ipv4')
    return await _cloudflare_domain_info(db, target, origin)


@router.get("")
async def list_pages(
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    rows = (await db.execute(select(PromoLandingPage).order_by(PromoLandingPage.updated_at.desc()))).scalars().all()
    return [_dto(row) for row in rows]


@router.post("", status_code=201)
async def create_page(
    data: LandingPageIn,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    exists = await db.scalar(select(PromoLandingPage.id).where(PromoLandingPage.domain == data.domain))
    if exists:
        raise HTTPException(409, "Цей домен уже прив'язаний до іншої промо-сторінки")
    config = _config(data)
    if _should_generate_initial_seo(config.get("seo") or {}):
        config["seo"] = generate_seo_payload(
            name=data.name.strip(), domain=data.domain, content=config.get("content") or {},
            variant_seed=f"create:{data.domain}:{secrets.token_hex(4)}",
        )
    row = PromoLandingPage(name=data.name.strip(), domain=data.domain, draft_config=config)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    security.record("promo.page.created", actor=who.login, reason=row.domain)
    return _dto(row)


class SeoGenerateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    domain: str
    content: ContentIn

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        return _domain(value)


@router.post("/{page_id}/seo-generate")
async def generate_page_seo(
    page_id: int,
    data: SeoGenerateIn,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    # A fresh nonce gives a new wording family on explicit regeneration, while all
    # facts still come only from current page content.
    seo = generate_seo_payload(
        name=data.name, domain=data.domain, content=data.content.model_dump(),
        variant_seed=f"regen:{page_id}:{row.version}:{secrets.token_hex(8)}",
    )
    security.record("promo.seo.generated", actor=who.login, reason=row.domain)
    return seo


@router.get("/{page_id}")
async def get_page(
    page_id: int,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    return _dto(row)


@router.put("/{page_id}")
async def update_page(
    page_id: int,
    data: LandingPageIn,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    conflict = await db.scalar(select(PromoLandingPage.id).where(
        PromoLandingPage.domain == data.domain,
        PromoLandingPage.id != page_id,
    ))
    if conflict:
        raise HTTPException(409, "Цей домен уже прив'язаний до іншої промо-сторінки")
    if row.domain != data.domain:
        old_status = await _domain_status(row.domain)
        if old_status.get("routePresent"):
            raise HTTPException(409, "Спочатку відключіть поточний домен у вкладці «Домен і деплой»")
    row.name = data.name.strip()
    row.domain = data.domain
    row.draft_config = _config(data)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    security.record("promo.page.saved", actor=who.login, reason=row.domain)
    return _dto(row)


@router.post("/{page_id}/publish")
async def publish_page(
    page_id: int,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    if not row.draft_config:
        raise HTTPException(400, "Немає чернетки для публікації")
    domain_state = await _domain_status(row.domain)
    if not domain_state.get("active"):
        raise HTTPException(409, "Домен ще не підключений. Відкрийте «Домен і деплой» та натисніть «Підключити домен»")
    row.published_config = json.loads(json.dumps(row.draft_config))
    row.is_published = True
    row.version = int(row.version or 0) + 1
    row.published_at = datetime.now(timezone.utc)
    row.updated_at = row.published_at
    await db.commit()
    await db.refresh(row)
    security.record("promo.page.published", actor=who.login, reason=f"{row.domain} v{row.version}")
    return _dto(row)


@router.post("/{page_id}/unpublish")
async def unpublish_page(
    page_id: int,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    row.is_published = False
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    security.record("promo.page.unpublished", actor=who.login, reason=row.domain)
    return _dto(row)


@router.delete("/{page_id}", status_code=204)
async def remove_page(
    page_id: int,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    domain = row.domain
    state = await _domain_status(domain)
    if state.get("routePresent"):
        raise HTTPException(409, "Спочатку відключіть домен, потім видаліть сторінку")
    await db.delete(row)
    await db.commit()
    security.record("promo.page.deleted", actor=who.login, reason=domain)
    return None


@router.get("/{page_id}/domain-status")
async def domain_status(
    page_id: int,
    domain: str | None = None,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    target = row.domain if not domain else _domain(domain)
    state = await _domain_status(target)
    origin = (state.get("dnsRequirements") or {}).get("ipv4")
    state["cloudflare"] = await _cloudflare_domain_info(db, target, origin)
    if state["cloudflare"].get("readyForProxyDeploy"):
        state["dns"]["cloudflareProxy"] = True
        state["dns"]["pointsHere"] = True
        state["dns"]["proxyAddresses"] = list(state["dns"].get("addresses") or [])
        state["dns"]["wrongAddresses"] = []
        state["dns"]["propagating"] = False
    if state.get("routePresent") and state.get("tls", {}).get("present"):
        state["live"] = await _public_site_probe(target)
    elif row.is_published:
        state["live"] = {"ok": False, "status": "preparing", "label": "Готується", "message": "Сторінка опублікована, але зовнішня адреса ще не готова."}
    else:
        state["live"] = {"ok": False, "status": "disabled", "label": "Вимкнено", "message": "Сторінка ще не доступна для відвідувачів."}
    state["page"] = {"published": bool(row.is_published), "version": row.version}
    return state


@router.post("/{page_id}/domain-connect")
async def domain_connect(
    page_id: int,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    pre = await _domain_status(row.domain)
    origin = (pre.get("dnsRequirements") or {}).get("ipv4")
    cf = await _cloudflare_domain_info(db, row.domain, origin)
    allow_proxy = bool(cf.get("readyForProxyDeploy"))
    state = await _controller("POST", "/v1/connect", domain=row.domain, extra={"allowProxy": allow_proxy})
    state["cloudflare"] = cf
    security.record("promo.domain.connected", actor=who.login, reason=f"{row.domain}; cloudflare={allow_proxy}")
    return state


@router.post("/{page_id}/domain-disconnect")
async def domain_disconnect(
    page_id: int,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    if row.is_published:
        row.is_published = False
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
    state = await _controller("POST", "/v1/disconnect", domain=row.domain)
    security.record("promo.domain.disconnected", actor=who.login, reason=row.domain)
    return state


@router.get("/{page_id}/stats")
async def page_stats(
    page_id: int,
    days: int = 30,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    if not await db.get(PromoLandingPage, page_id):
        raise HTTPException(404, "Промо-сторінку не знайдено")
    days = max(1, min(days, 366))
    rows = (await db.execute(
        select(PromoLandingDailyStat)
        .where(PromoLandingDailyStat.page_id == page_id)
        .order_by(PromoLandingDailyStat.day.desc())
        .limit(days)
    )).scalars().all()
    items = [{"day": row.day, "views": row.views, "clicks": row.clicks} for row in reversed(rows)]
    views = sum(i["views"] for i in items)
    clicks = sum(i["clicks"] for i in items)
    return {"views": views, "clicks": clicks, "ctr": round(clicks / views * 100, 2) if views else 0, "items": items}


def _html_response(document: str, headers: dict) -> HTMLResponse:
    hashes = {"'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"
              for script in re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", document, re.S | re.I)}
    google = "https://www.googletagmanager.com https://www.googleadservices.com https://googleads.g.doubleclick.net"
    policy = ("default-src 'none'; script-src " + " ".join(sorted(hashes)) + " " + google + "; "
              "style-src 'unsafe-inline'; img-src 'self' data: https://www.googleadservices.com https://*.google-analytics.com https://*.doubleclick.net https://www.google.com; "
              "connect-src https://www.google-analytics.com https://*.google-analytics.com https://www.googleadservices.com https://*.doubleclick.net https://*.googletagmanager.com https://www.google.com; "
              "frame-src https://www.googletagmanager.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")
    return HTMLResponse(document, headers={**headers, "Content-Security-Policy": policy,
                                         "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


@router.get("/{page_id}/preview", response_class=HTMLResponse)
async def preview_page(
    page_id: int,
    who: Principal = Depends(require_staff),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(PromoLandingPage, page_id)
    if not row:
        raise HTTPException(404, "Промо-сторінку не знайдено")
    return _html_response(_render(row, row.draft_config or {}, preview=True), headers={"Cache-Control": "no-store"})


async def _bump(db: AsyncSession, page_id: int, field: str) -> None:
    day = datetime.now(timezone.utc).date().isoformat()
    result = await db.execute(
        update(PromoLandingDailyStat)
        .where(PromoLandingDailyStat.page_id == page_id, PromoLandingDailyStat.day == day)
        .values({field: getattr(PromoLandingDailyStat, field) + 1})
    )
    if result.rowcount == 0:
        db.add(PromoLandingDailyStat(page_id=page_id, day=day, **{field: 1}))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        # Рідкісна гонка першого запиту дня: рядок уже вставив інший воркер.
        await db.execute(
            update(PromoLandingDailyStat)
            .where(PromoLandingDailyStat.page_id == page_id, PromoLandingDailyStat.day == day)
            .values({field: getattr(PromoLandingDailyStat, field) + 1})
        )
        await db.commit()


def _request_host(request: Request) -> str:
    # Proxy зберігає Host. Порт прибираємо, IPv6 для доменів тут не підтримуємо.
    return (request.headers.get("host") or "").split(":", 1)[0].lower().rstrip(".")


@router.get("/public/render/page", response_class=HTMLResponse, include_in_schema=False)
async def public_render(request: Request, db: AsyncSession = Depends(get_session)):
    domain = _request_host(request)
    row = await db.scalar(select(PromoLandingPage).where(
        PromoLandingPage.domain == domain,
        PromoLandingPage.is_published.is_(True),
    ))
    if not row or not row.published_config:
        raise HTTPException(404, "Сторінка не опублікована")
    if not _BOT_RE.search(request.headers.get("user-agent", "")):
        await _bump(db, row.id, "views")
    return _html_response(
        _render(row, row.published_config, preview=False),
        headers={
            "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
            "X-Robots-Tag": (row.published_config.get("seo") or {}).get("robots", DEFAULT_SEO["robots"]),
        },
    )


@router.get("/public/go/button", include_in_schema=False)
async def public_click(request: Request, db: AsyncSession = Depends(get_session)):
    domain = _request_host(request)
    row = await db.scalar(select(PromoLandingPage).where(
        PromoLandingPage.domain == domain,
        PromoLandingPage.is_published.is_(True),
    ))
    if not row or not row.published_config:
        raise HTTPException(404, "Сторінка не опублікована")
    target = ((row.published_config.get("content") or {}).get("button_url") or "").strip()
    try:
        target = _url(target)
    except ValueError:
        raise HTTPException(409, "Посилання кнопки не налаштоване")
    if not _BOT_RE.search(request.headers.get("user-agent", "")):
        await _bump(db, row.id, "clicks")
    from shop.services.analytics import attributed_button_url
    target = attributed_button_url(target, request.query_params, campaign=f"promo_{row.id}")
    return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})


def _abs(domain: str, path: str, *, preview: bool = False) -> str:
    if not path:
        return ""
    if path.startswith("/"):
        # Preview is opened from a blob URL in the dashboard. Keep local media
        # relative there so the dashboard can anchor it to its own /media/ host.
        # Production still gets an absolute promo-domain URL for SEO/social crawlers.
        return path if preview else f"https://{domain}{path}"
    return path


def _google_markup(google: dict, *, preview: bool = False) -> tuple[str, str, str]:
    verification = (google.get("search_console_verification") or "").strip()
    meta = f'<meta name="google-site-verification" content="{html.escape(verification, quote=True)}">' if verification else ""
    if preview or not google.get("enabled"):
        return meta, "", ""

    mode = google.get("mode") or "google_tag"
    consent = google.get("consent_mode") or "banner"
    google_tag_id = (google.get("google_tag_id") or "").strip()
    gtm_id = (google.get("gtm_container_id") or "").strip()
    ads_id = (google.get("ads_conversion_id") or "").strip()
    ads_label = (google.get("ads_conversion_label") or "").strip()

    head: list[str] = []
    body: list[str] = []
    tracking_ready = bool(gtm_id) if mode == "gtm" else bool(google_tag_id)

    if consent != "disabled" and tracking_ready:
        if consent == "banner":
            head.append(
                "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)};"
                "var promoConsentDefault='denied';try{if(localStorage.getItem('promo_google_consent')==='granted')promoConsentDefault='granted'}catch(e){};"
                "gtag('consent','default',{analytics_storage:promoConsentDefault,ad_storage:promoConsentDefault,"
                "ad_user_data:promoConsentDefault,ad_personalization:promoConsentDefault,wait_for_update:500});</script>"
            )
        else:
            head.append(
                "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)};"
                "gtag('consent','default',{analytics_storage:'granted',ad_storage:'granted',"
                "ad_user_data:'granted',ad_personalization:'granted',wait_for_update:500});</script>"
            )

    if mode == "gtm" and gtm_id:
        safe_id = html.escape(gtm_id, quote=True)
        head.append(
            "<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});"
            "var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';"
            "j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);})"
            f"(window,document,'script','dataLayer','{safe_id}');</script>"
        )
        body.append(
            f'<noscript><iframe src="https://www.googletagmanager.com/ns.html?id={safe_id}" height="0" width="0" '
            'style="display:none;visibility:hidden" title="Google Tag Manager"></iframe></noscript>'
        )
    elif mode == "google_tag" and google_tag_id:
        safe_id = html.escape(google_tag_id, quote=True)
        configs = [google_tag_id]
        if ads_id and ads_id not in configs:
            configs.append(ads_id)
        cfg = "".join(f"gtag('config',{json.dumps(x)});" for x in configs)
        head.append(
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={safe_id}"></script>'
            "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)};"
            f"gtag('js',new Date());{cfg}</script>"
        )

    if consent == "banner" and tracking_ready:
        body.append(
            '<div class="google-consent" id="googleConsent" hidden>'
            '<div><strong>Аналітика та реклама</strong><span>Ми можемо використовувати Google Analytics і Google Ads, щоб вимірювати ефективність сторінки.</span></div>'
            '<div class="google-consent-actions"><button type="button" data-consent="deny">Лише необхідні</button>'
            '<button type="button" data-consent="grant">Дозволити</button></div></div>'
        )

    send_to = f"{ads_id}/{ads_label}" if ads_id and ads_label else ""
    runtime = '''<script>(function(){
var mode=__MODE__,consentMode=__CONSENT__,sendTo=__SENDTO__;
function pushEvent(name,data){window.dataLayer=window.dataLayer||[];window.dataLayer.push(Object.assign({event:name},data||{}));}
function emitEvent(name,data){if(mode==='google_tag'&&typeof gtag==='function')gtag('event',name,data||{});else pushEvent(name,data);}
function setConsent(value){try{localStorage.setItem('promo_google_consent',value)}catch(e){};if(typeof gtag==='function')gtag('consent','update',{analytics_storage:value,ad_storage:value,ad_user_data:value,ad_personalization:value});pushEvent('promo_consent_update',{consent:value});}
if(consentMode==='banner'){var saved='';try{saved=localStorage.getItem('promo_google_consent')||''}catch(e){};var box=document.getElementById('googleConsent');if(saved==='granted'||saved==='denied')setConsent(saved);else if(box)box.hidden=false;if(box)box.addEventListener('click',function(e){var v=e.target&&e.target.getAttribute('data-consent');if(!v)return;setConsent(v==='grant'?'granted':'denied');box.hidden=true;});}
var cta=document.querySelector('.cta');if(cta&&cta.getAttribute('href')!=='#'){var entry=new URLSearchParams(location.search),dest=new URL(cta.getAttribute('href'),location.href);['source','medium','campaign','content','term'].forEach(function(k){var v=entry.get('utm_'+k);if(v)dest.searchParams.set('utm_'+k,v.slice(0,160));});cta.setAttribute('href',dest.pathname+dest.search);}
if(cta)cta.addEventListener('click',function(e){var href=cta.getAttribute('href');emitEvent('promo_cta_click',{promo_code:(document.querySelector('.code')||{}).textContent||'',destination:href});if(mode==='google_tag'&&sendTo&&typeof gtag==='function'){e.preventDefault();var done=false;var go=function(){if(done)return;done=true;location.href=href};gtag('event','conversion',{send_to:sendTo,event_callback:go});setTimeout(go,700);}});
})();</script>'''
    runtime = runtime.replace("__MODE__", json.dumps(mode)).replace("__CONSENT__", json.dumps(consent)).replace("__SENDTO__", json.dumps(send_to))
    body.append(runtime)
    return meta, "".join(head), "".join(body)


def _render(row: PromoLandingPage, config: dict, preview: bool) -> str:
    content = {**DEFAULT_CONTENT, **(config.get("content") or {})}
    seo = {**DEFAULT_SEO, **(config.get("seo") or {})}
    google = {**DEFAULT_GOOGLE, **(config.get("google") or {})}
    canonical = seo["canonical_url"] or f"https://{row.domain}/"
    og_title = seo["og_title"] or seo["title"] or content["title"]
    og_desc = seo["og_description"] or seo["description"]
    og_image = _abs(row.domain, seo["og_image"] or content["background_image"] or content["logo_image"], preview=preview)
    schema = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": seo["schema_name"] or seo["title"] or content["title"],
        "description": seo["schema_description"] or seo["description"],
        "url": canonical,
        "inLanguage": "uk-UA",
    }
    if og_image:
        schema["primaryImageOfPage"] = {"@type": "ImageObject", "url": og_image}

    esc = lambda value: html.escape(str(value or ""), quote=True)
    bg = esc(_abs(row.domain, content["background_image"], preview=preview))
    logo = esc(_abs(row.domain, content["logo_image"], preview=preview))
    cta = "#" if preview else "/go"
    preview_banner = '<div class="preview">Попередній перегляд чернетки</div>' if preview else ""
    logo_html = f'<img class="logo" src="{logo}" width="100" height="100" alt="Логотип" fetchpriority="high">' if logo else ""
    eyebrow_html = f'<div class="eyebrow">{esc(content["eyebrow"])}</div>' if content["eyebrow"] else ""
    footer_html = f'<p class="footer">{esc(content["footer_text"])}</p>' if content["footer_text"] else ""
    keywords = f'<meta name="keywords" content="{esc(seo["keywords"])}">' if seo["keywords"] else ""
    og_img_meta = f'<meta property="og:image" content="{esc(og_image)}"><meta name="twitter:image" content="{esc(og_image)}">' if og_image else ""
    site_meta = f'<meta property="og:site_name" content="{esc(seo["site_name"])}">' if seo["site_name"] else ""
    google_meta, google_head, google_body = _google_markup(google, preview=preview)

    # CSS — частина версійованого шаблону, а не користувацькі дані. У панелі
    # немає жодного поля, через яке його можна підмінити чи дописати script.
    return f'''<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(seo["title"] or content["title"])}</title>
<meta name="description" content="{esc(seo["description"])}">
<meta name="robots" content="{esc(seo["robots"])}">
{google_meta}
{keywords}
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:locale" content="{esc(seo["og_locale"])}">
<meta property="og:title" content="{esc(og_title)}">
<meta property="og:description" content="{esc(og_desc)}">
<meta property="og:url" content="{esc(canonical)}">
{site_meta}{og_img_meta}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(og_title)}">
<meta name="twitter:description" content="{esc(og_desc)}">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False).replace('</', '<\\/')}</script>
{google_head}
<style>
:root{{color-scheme:light;--ink:#111827;--muted:#5b6472;--accent:#1484e8;--accent2:#1e73be}}
*{{box-sizing:border-box}}html,body{{margin:0;min-height:100%;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink)}}
body{{min-height:100svh;display:grid;place-items:center;padding:24px;background:#eef2f6 {f'url("{bg}")' if bg else ''} center/cover no-repeat fixed}}
body:before{{content:"";position:fixed;inset:0;background:rgba(12,20,32,.12);pointer-events:none}}
.card{{position:relative;width:min(100%,520px);padding:44px 34px 32px;background:rgba(255,255,255,.97);border:1px solid rgba(17,24,39,.10);border-radius:20px;box-shadow:0 24px 70px rgba(15,23,42,.22);text-align:center}}
.logo{{display:block;margin:0 auto 28px;border-radius:20px;object-fit:cover}}.eyebrow{{margin-bottom:8px;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--accent2)}}
h1{{margin:0 0 28px;font-size:clamp(26px,5vw,38px);line-height:1.12;letter-spacing:-.025em}}.label{{margin:0 0 10px;color:var(--muted)}}
.code{{display:inline-block;margin:0 0 20px;padding:12px 18px;border:1px dashed #aab4c3;border-radius:12px;background:#f8fafc;font:800 22px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.05em;user-select:all}}
.copyhint{{display:block;margin-top:-12px;margin-bottom:20px;font-size:11px;color:#8a94a3}}.desc,.validity{{margin:0 auto 14px;max-width:420px;line-height:1.55;color:#374151}}.validity{{font-size:14px;color:var(--muted)}}
.cta{{display:inline-flex;align-items:center;justify-content:center;min-width:220px;margin-top:14px;padding:15px 26px;border-radius:999px;background:linear-gradient(90deg,var(--accent),var(--accent2));color:#fff;text-decoration:none;font-weight:800;box-shadow:0 10px 24px rgba(20,132,232,.24)}}.cta:hover{{filter:brightness(.98);transform:translateY(-1px)}}
.footer{{margin:24px 0 0;font-size:12px;line-height:1.45;color:#8a94a3}}.preview{{position:fixed;top:12px;left:50%;z-index:3;transform:translateX(-50%);padding:8px 12px;border-radius:999px;background:#111827;color:#fff;font-size:12px;font-weight:700}}
.google-consent{{position:fixed;z-index:20;left:16px;right:16px;bottom:16px;margin:auto;max-width:760px;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:16px;background:#111827;color:#fff;border-radius:14px;box-shadow:0 16px 50px rgba(0,0,0,.28);text-align:left}}.google-consent[hidden]{{display:none}}.google-consent>div:first-child{{display:grid;gap:4px}}.google-consent span{{font-size:12px;line-height:1.4;color:#d1d5db}}.google-consent-actions{{display:flex;gap:8px;flex:0 0 auto}}.google-consent button{{border:0;border-radius:999px;padding:9px 12px;font:700 12px/1 inherit;cursor:pointer}}
@media(max-width:560px){{body{{padding:16px}}.card{{padding:34px 22px 28px;border-radius:17px}}.google-consent{{align-items:stretch;flex-direction:column}}.google-consent-actions button{{flex:1}}}}
@media(prefers-reduced-motion:no-preference){{.cta{{transition:transform .18s ease,filter .18s ease}}}}
</style>
</head>
<body>{preview_banner}
<main class="card">
{logo_html}{eyebrow_html}
<h1>{esc(content["title"])}</h1>
<p class="label">{esc(content["promo_label"])}</p>
<div class="code">{esc(content["promo_code"])}</div><span class="copyhint">Код можна виділити та скопіювати</span>
<p class="desc">{esc(content["description"])}</p>
<p class="validity">{esc(content["validity_text"])}</p>
<a class="cta" href="{esc(cta)}" rel="noopener noreferrer">{esc(content["button_text"])}</a>
{footer_html}
</main>
{google_body}
</body></html>'''
