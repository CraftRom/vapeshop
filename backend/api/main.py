from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from api.auth import create_token, verify_credentials
from api.routers import broadcasts, catalog, customers, orders, promos, stats
from api.schemas import LoginIn, TokenOut
from shop.config import settings
from shop.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    log = logging.getLogger("api")
    log.info("Дашборд очікує логін: %r", settings.dashboard_login)
    if settings.dashboard_password == "admin":
        log.warning(
            "DASHBOARD_PASSWORD не змінено з дефолтного. "
            "Задайте його в .env і перестворіть контейнер: docker compose up -d --force-recreate api"
        )
    yield


app = FastAPI(title=f"{settings.shop_name} — Dashboard API", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/auth/login", response_model=TokenOut, tags=["auth"])
async def login(data: LoginIn):
    if not verify_credentials(data.login, data.password):
        # Логуємо тільки логін і довжину пароля — сам пароль у логи не потрапляє.
        logging.getLogger("api").warning(
            "Невдалий вхід: отримано логін %r (довжина пароля %d); очікується логін %r "
            "(довжина пароля %d)",
            data.login,
            len(data.password),
            settings.dashboard_login,
            len(settings.dashboard_password),
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний логін або пароль")
    return TokenOut(access_token=create_token(data.login))


@app.get("/api/health", tags=["service"])
async def health():
    return {"status": "ok", "shop": settings.shop_name}


app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(customers.router, prefix="/api/customers", tags=["customers"])
app.include_router(promos.router, prefix="/api/promos", tags=["promos"])
app.include_router(broadcasts.router, prefix="/api/broadcasts", tags=["broadcasts"])
