"""Opaque HttpOnly sessions, synchronizer CSRF tokens and server-side logout."""
from __future__ import annotations
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from fastapi import HTTPException, Request, Response
from api.auth import Principal, _live, password_fingerprint
from shop.config import settings
from shop.entities import OperatorRole
from shop.services.shop_settings import current


def secure_cookie() -> bool:
    return settings.public_url.startswith("https://")


def cookie_name() -> str:
    return "__Host-shop_session" if secure_cookie() else "shop_dev_session"


def check_browser_request(request: Request) -> None:
    # A custom header disallows simple cross-origin forms, including login CSRF.
    if request.headers.get("x-dashboard-request") != "1":
        raise HTTPException(403, "Потрібен захищений запит панелі")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Сторонній сайт")
    origin = request.headers.get("origin")
    if origin:
        origins = set(settings.cors_list)
        public = urlsplit(settings.public_url)
        if public.scheme and public.netloc:
            origins.add(f"{public.scheme}://{public.netloc}")
        if origin not in origins:
            raise HTTPException(403, "Сторонній сайт")


def digest_cookie(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def profile(principal: Principal, csrf: str) -> dict:
    return {"role": principal.role.value, "name": principal.name or principal.login, "csrf_token": csrf}


async def open_session(request: Request, response: Response, repo, principal: Principal) -> dict:
    # Successful login always rotates the session ID. No session fixation.
    old = request.cookies.get(cookie_name())
    if old:
        await repo.delete_dashboard_session(digest_cookie(old))
    raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    hours = min(72, max(1, current().jwt_ttl_hours or settings.jwt_ttl_hours))
    await repo.create_dashboard_session({"id": digest_cookie(raw), "operator_id": principal.operator_id,
        "login": principal.login, "csrf_token": csrf, "auth_version": principal.auth_version,
        "owner_fingerprint": password_fingerprint() if principal.operator_id == 0 else "",
        "created_at": now, "last_seen_at": now, "expires_at": now + timedelta(hours=hours)})
    response.set_cookie(cookie_name(), raw, max_age=hours * 3600, path="/",
                        secure=secure_cookie(), httponly=True, samesite="strict")
    return profile(principal, csrf)


async def cookie_principal(request: Request, repo) -> Principal:
    raw = request.cookies.get(cookie_name(), "")
    if not raw or len(raw) > 128:
        raise HTTPException(401, "Потрібна авторизація")
    digest = digest_cookie(raw)
    row = await repo.get_dashboard_session(digest)
    now = datetime.now(timezone.utc)
    idle = min(1440, max(5, settings.dashboard_idle_minutes))
    if not row or aware(row["expires_at"]) <= now or aware(row["last_seen_at"]) + timedelta(minutes=idle) <= now:
        if row:
            await repo.delete_dashboard_session(digest)
        raise HTTPException(401, "Сесія завершилась — увійдіть знову")
    if row["operator_id"] == 0 and (row["owner_fingerprint"] != password_fingerprint() or row["login"] != settings.dashboard_login):
        raise HTTPException(401, "Пароль змінено — увійдіть знову")
    principal = await _live(Principal(row["login"], "Адміністратор", OperatorRole.SYSADMIN,
                                    row["operator_id"], row["auth_version"]), repo, report_role_change=False)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_browser_request(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode(), row["csrf_token"].encode()):
            raise HTTPException(403, "Захист запиту: оновіть сторінку")
    if now - aware(row["last_seen_at"]) > timedelta(seconds=60):
        await repo.touch_dashboard_session(digest, now)
    request.state.dashboard_session = row
    return principal
