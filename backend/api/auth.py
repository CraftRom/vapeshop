from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from dataclasses import dataclass

from shop.config import settings
from shop.entities import OperatorRole
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.shop_settings import current
from shop.services.passwords import verify_password

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


@dataclass
class Principal:
    """Хто саме працює в панелі цього запиту."""

    login: str
    name: str
    role: OperatorRole
    operator_id: int  # 0 — адміністратор із .env, його немає в таблиці

    @property
    def is_sysadmin(self) -> bool:
        """Лише власник .env. Йому одному дозволена інфраструктура."""
        return self.role == OperatorRole.SYSADMIN

    @property
    def is_admin(self) -> bool:
        return self.role in (OperatorRole.SYSADMIN, OperatorRole.ADMIN)


def password_fingerprint() -> str:
    """Відбиток чинного пароля з .env. Змінився пароль — змінився відбиток.

    Токен системного адміністратора не має за собою рядка в базі, тож
    відкликати його не було чим: після зміни DASHBOARD_PASSWORD старий
    токен працював до кінця строку. Якщо пароль міняють саме тому, що він
    міг витекти, це означає, що зловмисник лишався всередині ще години.

    Сам пароль у токен не потрапляє — лише відбиток, солений JWT-секретом.
    """
    material = f"{settings.dashboard_password}:{settings.jwt_secret}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def create_token(login: str, role: OperatorRole, operator_id: int = 0, name: str = "",
                 ttl_hours: int | None = None) -> str:
    """ttl_hours=None — беремо чинне значення з налаштувань панелі."""
    hours = ttl_hours or current().jwt_ttl_hours or settings.jwt_ttl_hours
    payload = {
        "sub": login,
        "role": role.value,
        "oid": operator_id,
        "name": name,
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
        "iat": datetime.now(timezone.utc),
    }
    if operator_id == 0:
        payload["pv"] = password_fingerprint()
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _decode(creds: HTTPAuthorizationCredentials | None) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Потрібна авторизація")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сесія завершилась — увійдіть знову")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недійсний токен")

    # Токени, видані до появи ролей, вважаємо адмінськими: їх міг отримати
    # лише власник пароля з .env
    try:
        role = OperatorRole(payload.get("role", OperatorRole.SYSADMIN.value))
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недійсний токен")

    principal = Principal(
        login=payload["sub"], name=payload.get("name", ""),
        role=role, operator_id=int(payload.get("oid", 0)),
    )

    # Токен сисадміна дійсний, поки не змінився пароль у .env
    if principal.operator_id == 0 and payload.get("pv") != password_fingerprint():
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Пароль змінено — увійдіть знову"
        )

    return principal


async def _live(principal: Principal, repo) -> Principal:
    """Звіряє токен із чинним станом менеджера в базі.

    Підпис токена доводить лише те, що ми його колись видали. Усе, що
    сталося після видачі, він не знає: вимкнення менеджера, зниження ролі,
    зміну пароля. Без цієї звірки звільнений менеджер працював у панелі до
    кінця строку токена — за замовчуванням до дванадцяти годин, — а
    знижений до менеджера адміністратор стільки ж лишався адміністратором.

    Ціна — один запит до бази на звернення. Для навантаження цієї панелі
    це ніщо, а альтернативи (короткий строк життя токена, чорний список)
    або вибивають людину з роботи щопівгодини, або вимагають окремого
    сховища, яке теж треба чистити.
    """
    if principal.operator_id == 0:
        return principal  # адміністратор із .env, його в таблиці немає

    operator = await repo.get_operator(principal.operator_id)
    if not operator or not operator.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Обліковий запис вимкнено"
        )
    if operator.role != principal.role:
        # Роль могли не лише знизити, а й підвищити. Приймаємо чинну з бази,
        # а не з токена: джерело правди тут одне.
        principal.role = operator.role
    principal.name = operator.name or principal.name
    return principal


async def require_staff(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    repo: Repository = Depends(get_repo),
) -> Principal:
    """Будь-хто, хто увійшов у панель: адміністратор або менеджер."""
    return await _live(_decode(creds), repo)


async def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    repo: Repository = Depends(get_repo),
) -> Principal:
    """Лише адміністратор: керування менеджерами й повні налаштування."""
    principal = await _live(_decode(creds), repo)
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Дія доступна лише адміністратору")
    return principal


async def require_sysadmin(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
    repo: Repository = Depends(get_repo),
) -> Principal:
    """Лише власник .env.

    Окремий рівень поверх адміністратора: журнал містить IP клієнтів,
    логіни, шляхи запитів і тексти помилок. Це не те, що варто відкривати
    кожному, хто керує каталогом.
    """
    principal = await _live(_decode(creds), repo)
    if not principal.is_sysadmin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Дія доступна лише системному адміністратору",
        )
    return principal


async def authenticate(repo, login: str, password: str) -> Principal | None:
    """Спершу адміністратор із .env, потім менеджери з бази.

    Порядок саме такий, щоб у щойно розгорнуту систему можна було увійти,
    коли менеджерів ще не створено.
    """
    if verify_credentials(login, password):
        return Principal(login=login, name="Адміністратор",
                         role=OperatorRole.SYSADMIN, operator_id=0)

    operator = await repo.get_operator_by_login(login.strip())
    if not operator or not operator.is_active:
        return None
    if not verify_password(password, operator.password_hash):
        return None

    await repo.update_operator(operator.id, {"last_login_at": datetime.now(timezone.utc)})
    return Principal(login=operator.login, name=operator.name,
                     role=operator.role, operator_id=operator.id)
