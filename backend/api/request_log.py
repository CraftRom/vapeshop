"""Журнал запитів до API.

Кожен запит — один рядок JSON із тим самим набором полів, що й у
serverless-платформ: ідентифікатор, метод, шлях, хост, IP, агент, код
відповіді, тривалість. Саме за цим набором потім шукають: «усі 500 за
годину», «скільки часу займає /api/stats», «звідки прийшов цей запит».

Ідентифікатор запиту кладеться і в заголовок відповіді (X-Request-Id):
коли клієнт скаржиться, він може назвати номер, і рядок знаходиться
одним grep замість перебору за часом.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from shop.security_log import request_context as security_context

log = logging.getLogger("api.request")

# Доступний з будь-якого місця обробки запиту — щоб прикладні події
# (створено замовлення, невдалий вхід) можна було зв'язати з запитом,
# який їх спричинив.
current_request_id: ContextVar[str] = ContextVar("request_id", default="")

# Шляхи, які смикають моніторинг і планувальник. Пишемо їх на DEBUG:
# інакше вони витіснять із журналу все живе.
# /api/logs тут не випадково: сторінка журналу опитує його кожні десять
# секунд, і без цього перегляд журналу заповнював би журнал сам собою —
# рівно тими записами, крізь які потім довелося б продиратись.
QUIET_PATHS = ("/api/health", "/api/debug/", "/api/logs")


def client_ip(request: Request) -> str:
    """IP клієнта з урахуванням проксі.

    За nginx усі запити приходять з адреси контейнера, тому справжня
    адреса — у заголовках від проксі.

    CF-Connecting-IP перевіряємо першим: його ставить Cloudflare і, на
    відміну від X-Forwarded-For, підмінити його ззовні не можна — усе, що
    надіслав клієнт, Cloudflare перезаписує. X-Forwarded-For лишається
    запасним варіантом на випадок, коли трафік іде повз CDN.
    """
    direct = request.headers.get("cf-connecting-ip", "").strip()
    if direct:
        return direct
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def client_country(request: Request) -> str:
    """Країна за IP — від Cloudflare, безкоштовно й без сторонніх сервісів.

    Для більшості подій вона не важить, але саме вона відповідає на
    питання, яке ставлять першим: це наш покупець із поганим зʼєднанням
    чи хтось перебирає адреси з-за кордону. Магазин возить лише по
    Україні, тож звернення звідусіль інде вже саме по собі показове.

    XX — Cloudflare не визначив, T1 — мережа Tor. Порожньо означає, що
    трафік ішов повз CDN, а не що країни немає.
    """
    return request.headers.get("cf-ipcountry", "").strip().upper()


def _identify(request: Request) -> tuple[str, str]:
    """Логін і роль із токена, якщо він є.

    Помилку розбору ковтаємо навмисно: журнал не має падати через кривий
    чи протермінований токен — запит однаково буде відхилено далі, і саме
    цей факт цікаво побачити в журналі.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return "", ""
    try:
        import jwt

        from shop.config import settings

        payload = jwt.decode(header[7:], settings.jwt_secret, algorithms=["HS256"])
        return str(payload.get("sub", "")), str(payload.get("role", ""))
    except Exception:
        return "", "невалідний токен"


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = current_request_id.set(request_id)
        # Той самий контекст доклеюється до кожної події безпеки, хоч би
        # з якої глибини її записали. Без цього найважливіші події —
        # відхилення підпису Mini App — не мали навіть IP.
        ctx_token = security_context.set({
            "requestId": request_id,
            "ip": client_ip(request),
            "country": client_country(request),
            "userAgent": request.headers.get("user-agent", ""),
            "path": request.url.path,
            "method": request.method,
        })
        started = time.perf_counter()

        # Хто робить запит — визначаємо тут, а не в кожній залежності.
        # Інакше дія лишалася б непідписаною скрізь, де обробник бере
        # токен по-своєму, і саме там це найпотрібніше.
        actor, actor_role = _identify(request)

        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        except Exception:
            # Виняток теж має лишити слід із тим самим requestId, інакше
            # у журналі буде трейсбек без жодної прив'язки до запиту.
            log.exception("Необроблена помилка", extra={"requestId": request_id})
            raise
        finally:
            duration = round((time.perf_counter() - started) * 1000, 1)
            quiet = request.url.path.startswith(QUIET_PATHS)
            log.log(
                logging.DEBUG if (quiet and status < 400) else
                logging.WARNING if status >= 400 else logging.INFO,
                "%s %s → %s", request.method, request.url.path, status,
                extra={
                    "event": "http.request",
                    "requestId": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query),
                    "host": request.headers.get("host", ""),
                    "ip": client_ip(request),
                    "country": client_country(request),
                    "userAgent": request.headers.get("user-agent", ""),
                    "status": status,
                    "durationMs": duration,
                    # Хто саме зробив запит. Без цього в журналі видно «хтось
                    # змінив статус замовлення», і з'ясувати хто — ніяк:
                    # IP у менеджерів динамічний, а за токеном не шукають.
                    "actor": actor,
                    "actorRole": actor_role,
                    "referer": request.headers.get("referer", ""),
                },
            )
            current_request_id.reset(token)
            security_context.reset(ctx_token)
