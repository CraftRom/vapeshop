from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from api.auth import authenticate, create_token
from api.routers import (
    broadcasts, catalog, cron, customers, orders, promos, settings as settings_router,
    operators, shop as shop_router, stats, telegram,
)
from api.schemas import LoginIn, TokenOut
from shop.config import settings
from shop.services.shop_settings import current
from shop.repo.factory import get_repo
from shop.db import init_db

from shop.build import BUILD as _BUILD

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = logging.getLogger("api")

    if settings.db_backend == "firestore":
        log.info("База: Firestore (проєкт %s)", settings.firebase_project or "за замовчуванням")
        log.info("Дашборд очікує логін: %r", settings.dashboard_login)
        yield
        return

    if settings.serverless:
        # На Vercel схему накочує Alembic окремою командою, а не кожен інстанс
        log.info("Serverless-режим: init_db пропущено")
        yield
        return

    try:
        await init_db()
    except Exception as exc:
        # Без цього блоку API просто падав у краш-цикл, nginx віддавав 502,
        # а в панелі це виглядало як проблема з логіном.
        log.error("=" * 70)
        log.error("НЕ ВДАЛОСЯ ПІДКЛЮЧИТИСЬ ДО БАЗИ: %s", exc)
        log.error("Перевірте POSTGRES_PASSWORD у .env.")
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


# Документація закрита за замовчуванням.
#
# Відкритий /openapi.json — це готова карта атаки: усі адмінські маршрути,
# назви полів і формати. Розробнику вона потрібна, тож вмикається явно
# змінною ENABLE_API_DOCS=true, і тільки в неробочому середовищі.
_docs_on = settings.enable_api_docs

app = FastAPI(
    title=f"{settings.shop_name} — Dashboard API",
    version="1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs_on else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/auth/login", response_model=TokenOut, tags=["auth"])
async def login(data: LoginIn, repo=Depends(get_repo)):
    principal = await authenticate(repo, data.login, data.password)
    if principal is None:
        # Логуємо лише логін і довжину пароля — сам пароль у логи не потрапляє
        logging.getLogger("api").warning(
            "Невдалий вхід: логін %r, довжина пароля %d", data.login, len(data.password)
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний логін або пароль")
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
    # Якщо ці два поля розходяться — очистка працює; якщо в raw лежить
    # «%28default%29», а в effective те саме — у продакшені старий код.
    # Не секрет: це ідентифікатор бази, а не доступ до неї.
    import os as _os

    return {
        "status": "ok" if not problems else "misconfigured",
        "build": _BUILD,
        "shop": settings.shop_name,
        "db_backend": settings.db_backend,
        "serverless": settings.serverless,
        "firebase_database": {
            "raw": _os.environ.get("FIREBASE_DATABASE", ""),
            "effective": settings.firebase_database,
        },
        "webhook_configured": bool(
            settings.webhook_secret and (current().public_url or settings.public_url)
        ),
        "missing_env": problems,
    }


@app.get("/api/debug/firestore", tags=["service"])
async def debug_firestore():
    """Що насправді бачить клієнт Firestore.

    Досі про причину «Invalid database id» доводилося здогадуватись: логи
    показують текст помилки, але не показують, з яким ідентифікатором бази
    клієнт був створений і які версії бібліотек реально стоять у збірці.
    Тут — і те, і те, плюс один найдешевший реальний запит до бази.

    Без авторизації, як і /api/health: коли база лежить, у панель не увійти,
    а саме тоді ця сторінка й потрібна. Секретів не віддає — лише
    ідентифікатори проєкту та бази й номери версій.
    """
    result: dict = {"build": _BUILD}

    try:
        from shop.repo.factory import _get_firestore_store

        store = _get_firestore_store()
        client = store.client
        result["client"] = {
            # Приватні атрибути читаємо навмисно: публічного способу спитати
            # клієнта про його базу SDK не дає, а саме це нас і цікавить.
            "project": getattr(client, "project", None),
            "database": getattr(client, "_database", None),
            "database_string": getattr(client, "_database_string", None),
        }
    except Exception as exc:
        result["client"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import google.api_core.version as _api_core_version
        import grpc as _grpc
        from google.cloud.firestore import __version__ as _fs_version

        result["versions"] = {
            "google-cloud-firestore": _fs_version,
            "google-api-core": _api_core_version.__version__,
            "grpcio": _grpc.__version__,
        }
    except Exception as exc:
        result["versions"] = {"error": f"{type(exc).__name__}: {exc}"}

    # Найдешевший можливий запит: один документ із колекції, якої може й не
    # бути. Порожня відповідь — теж успіх, нас цікавить сам факт зʼєднання.
    try:
        from shop.repo.factory import _get_firestore_store

        store = _get_firestore_store()
        await store.client.collection("__diag__").limit(1).get()
        result["probe"] = {"ok": True}
    except Exception as exc:
        result["probe"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}

    return result


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
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(customers.router, prefix="/api/customers", tags=["customers"])
app.include_router(promos.router, prefix="/api/promos", tags=["promos"])
app.include_router(broadcasts.router, prefix="/api/broadcasts", tags=["broadcasts"])
app.include_router(operators.router, prefix="/api/operators", tags=["operators"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
# Вітрина Mini App — окрема автентифікація (Telegram initData), не JWT панелі
app.include_router(shop_router.router, prefix="/api/shop", tags=["shop"])
app.include_router(cron.router, prefix="/api/cron", tags=["cron"])
app.include_router(telegram.router, prefix="/api", tags=["telegram"])
