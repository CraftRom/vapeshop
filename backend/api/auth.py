from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shop.config import settings

security = HTTPBearer(auto_error=False)


def verify_credentials(login: str, password: str) -> bool:
    """Порівняння сталого часу.

    compare_digest з рядками працює лише для ASCII — на кирилиці кидає
    TypeError. Тому порівнюємо байти: так проходить будь-який символ.
    """
    login_ok = hmac.compare_digest(
        login.encode("utf-8"), settings.dashboard_login.encode("utf-8")
    )
    password_ok = hmac.compare_digest(
        password.encode("utf-8"), settings.dashboard_password.encode("utf-8")
    )
    return login_ok and password_ok


def create_token(login: str) -> str:
    payload = {
        "sub": login,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Потрібна авторизація")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сесія завершилась — увійдіть знову")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недійсний токен")
    return payload["sub"]
