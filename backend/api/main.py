from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from api.auth import authenticate, create_token
from api.routers import (
    backups as backups_router, broadcasts, catalog, customers,
    logs as logs_router, media as media_router,
    orders, promos,
    settings as settings_router, operators, shop as shop_router, stats, telegram,
)
from api.schemas import LoginIn, TokenOut
from shop.config import settings
from shop.services.shop_settings import current
from shop.repo.factory import get_repo
from shop.db import check_db

from bot.version import BOT_VERSION as _BOT_VERSION
from shop.build import BUILD as _BUILD
from shop.paths import describe as _storage

from shop.logging_setup import setup as setup_logging

setup_logging("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = logging.getLogger("api")

    # Схему накочує сервіс migrate до старту API. Тут лише перевіряємо
    # звʼязок, і це принципово: init_db() робить create_all, а він при
    # кількох воркерах перегонить сам себе — обидва бачать, що таблиці
    # немає, обидва створюють, другий падає з «table already exists».
    # Воркер помирає, uvicorn піднімає новий, той падає так само. У логах
    # видно лише «Child process died» без причини.
    try:
        await check_db()
    except Exception as exc:
        # Без цього блоку API просто падав у краш-цикл, nginx віддавав 502,
        # а в панелі це виглядало як проблема з логіном.
        log.error("=" * 70)
        log.error("НЕ ВДАЛОСЯ ПІДКЛЮЧИТИСЬ ДО БАЗИ: %s", exc)
        log.error("Перевірте, що сервіс migrate відпрацював, і POSTGRES_PASSWORD у .env.")
        log.error(
            "Якщо ви змінили пароль ПІСЛЯ першого запуску — Postgres його не підхопить: "
            "пароль задається лише при створенні тому. Або поверніть старий пароль, "
            "або перестворіть базу (УВАГА, це зітре дані): "
            "docker compose down -v && docker compose up -d"
        )
        log.error("=" * 70)
        raise

    log.info("Дашборд очікує логін: %r", settings.dashboard_login)
    if settings.dashboard_password == "admin":
        log.warning(
            "DASHBOARD_PASSWORD не змінено з дефолтного. "
            "Задайте його в .env і перестворіть контейнер: docker compose up -d --force-recreate api"
        )
    yield

    # Бот, яким API шле сповіщення, тримає власну сесію aiohttp. Ніхто її
    # не закривав, тому кожне вимкнення контейнера давало в журналі
    # «Unclosed client session» рівнем error — а на кожен error іде
    # сповіщення в Telegram. Через це звичайний деплой виглядав як аварія,
    # і справжні помилки губилися серед хибних тривог.
    from api.routers.telegram import close_bot

    await close_bot()


# Документація закрита за замовчуванням.
#
# Відкритий /openapi.json — це готова карта атаки: усі адмінські маршрути,
# назви полів і формати. Розробнику вона потрібна, тож вмикається явно
# змінною ENABLE_API_DOCS=true, і тільки в неробочому середовищі.
_docs_on = settings.enable_api_docs

app = FastAPI(
    title=f"{settings.shop_name} — Dashboard API",
    # Версія API. Піднімається разом із помітними змінами контракту:
    # три ролі замість двох і новий розділ журналу — саме такий випадок.
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs_on else None,
)

from api.request_log import RequestLogMiddleware, client_ip, current_request_id

# Порядок важливий: журнал ставимо першим, щоб він бачив і ті запити,
# які CORS відхилить, — саме вони найчастіше й спантеличують.
app.add_middleware(RequestLogMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/auth/login", response_model=TokenOut, tags=["auth"])
async def login(request: Request, data: LoginIn, repo=Depends(get_repo)):
    auth_log = logging.getLogger("api.auth")
    context = {
        "requestId": current_request_id.get(),
        "login": data.login,
        "ip": client_ip(request),
        "userAgent": request.headers.get("user-agent", ""),
    }

    principal = await authenticate(repo, data.login, data.password)
    if principal is None:
        # Пароль у журнал не потрапляє ніколи — лише його довжина. Цього
        # досить, щоб відрізнити помилку набору від перебору, і замало,
        # щоб журнал сам став витоком.
        auth_log.warning(
            "Невдалий вхід: %s", data.login,
            extra={**context, "event": "auth.login.failed",
                   "passwordLength": len(data.password)},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний логін або пароль")

    auth_log.info(
        "Вхід: %s", data.login,
        extra={**context, "event": "auth.login.ok",
               "role": principal.role.value, "operatorId": principal.operator_id},
    )
    return TokenOut(
        access_token=create_token(
            principal.login, principal.role, principal.operator_id, principal.name
        ),
        role=principal.role.value,
        name=principal.name or principal.login,
    )


@app.get("/api/health", tags=["service"])
async def health():
    """Діагностика розгортання.

    Навмисно без авторизації: якщо конфігурація зламана, увійти неможливо,
    і саме тоді потрібно розуміти причину. Значень змінних не розкриваємо —
    лише назви тих, яких бракує.
    """
    problems = settings.missing_required()
    # Сире значення змінної поруч із тим, що з нього вийшло після очистки.
    return {
        "status": "ok" if not problems else "misconfigured",
        "build": _BUILD,
        "botVersion": _BOT_VERSION,
        "storage": _storage(),
        "shop": settings.shop_name,
        "webhook_configured": bool(
            settings.webhook_secret and (current().public_url or settings.public_url)
        ),
        "missing_env": problems,
    }


@app.get("/api/debug/database", tags=["service"])
async def debug_database():
    """Чи жива база просто зараз.

    Без авторизації, як і /api/health: коли база лягла, у панель не увійти,
    а саме тоді ця сторінка й потрібна. Адреси й паролі не віддає — лише
    факт зʼєднання, версію сервера й час найдешевшого запиту.
    """
    import time

    from sqlalchemy import text

    from shop.db import SessionMaker

    started = time.monotonic()
    try:
        async with SessionMaker() as session:
            version = (await session.execute(text("SELECT version()"))).scalar_one()
            await session.execute(text("SELECT 1"))
        return {
            "build": _BUILD,
            "ok": True,
            "server": str(version)[:80],
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
        }
    except Exception as exc:
        return {
            "build": _BUILD,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }


@app.get("/api/debug/routing", tags=["service"])
async def debug_routing(request: Request):
    """Показує, який шлях реально дійшов до застосунку.

    Потрібно, коли платформа переписує URL: якщо сюди приходить не той шлях,
    що в адресному рядку, значить проблема в маршрутизації, а не в коді.
    """
    return {
        "path_received": request.url.path,
        "root_path": request.scope.get("root_path", ""),
        "expected": "/api/debug/routing",
        "routing_ok": request.url.path.endswith("/api/debug/routing"),
    }


app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(logs_router.router)
app.include_router(backups_router.router)
app.include_router(media_router.router)
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(customers.router, prefix="/api/customers", tags=["customers"])
app.include_router(promos.router, prefix="/api/promos", tags=["promos"])
app.include_router(broadcasts.router, prefix="/api/broadcasts", tags=["broadcasts"])
app.include_router(operators.router, prefix="/api/operators", tags=["operators"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
# Вітрина Mini App — окрема автентифікація (Telegram initData), не JWT панелі
app.include_router(shop_router.router, prefix="/api/shop", tags=["shop"])
app.include_router(telegram.router, prefix="/api", tags=["telegram"])
