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
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from shop.config import settings
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
QUIET_PATHS = ("/api/health", "/api/debug/", "/api/logs", "/api/shop/client-log")

_SECRET_QUERY_NAMES = {"token", "secret", "password", "bot_token", "api_key", "init_data", "initdata", "key", "csrf_token", "sid", "access_token"}

def safe_query(request: Request) -> str:
    """Query string без секретів; службові токени не повинні жити в логах."""
    items = []
    for key, value in request.query_params.multi_items():
        items.append((key, "[REDACTED]" if key.lower() in _SECRET_QUERY_NAMES else value))
    from urllib.parse import urlencode
    return urlencode(items, doseq=True)



def trusted_proxy(request: Request) -> bool:
    try:
        peer = ipaddress.ip_address(request.client.host if request.client else "")
        return any(peer in ipaddress.ip_network(net.strip()) for net in settings.trusted_proxy_networks.split(",") if net.strip())
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    if trusted_proxy(request):
        try:
            return str(ipaddress.ip_address(request.headers.get("x-real-ip", "")))
        except ValueError:
            pass
    return request.client.host if request.client else ""


def client_country(request: Request) -> str:
    country = request.headers.get("cf-ipcountry", "").strip().upper()
    return country if trusted_proxy(request) and re.fullmatch(r"[A-Z0-9]{2}", country) else ""


def safe_path(path: str) -> str:
    path = re.sub(r"(/api/telegram/)[^/]+", r"\1[REDACTED]", path)
    return re.sub(r"(/api/integrations/salesdrive/webhook/)[^/]+", r"\1[REDACTED]", path)


def safe_referer(value: str) -> str:
    try:
        url = urlsplit(value[:2048])
        # Referrer is diagnostic context, never a place for query strings or fragments.
        return urlunsplit((url.scheme, url.hostname or "", safe_path(url.path), "", ""))
    except ValueError:
        return ""


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

        payload = jwt.decode(header[7:], settings.jwt_secret, algorithms=["HS256"], issuer="shop-dashboard", audience="shop-api")
        return str(payload.get("sub", "")), str(payload.get("role", ""))
    except Exception:
        return "", "невалідний токен"


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied_id = request.headers.get("x-request-id", "")
        request_id = supplied_id if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", supplied_id) else uuid.uuid4().hex[:16]
        token = current_request_id.set(request_id)
        # Той самий контекст доклеюється до кожної події безпеки, хоч би
        # з якої глибини її записали. Без цього найважливіші події —
        # відхилення підпису Mini App — не мали навіть IP.
        ctx_token = security_context.set({
            "requestId": request_id,
            "ip": client_ip(request),
            "country": client_country(request),
            "userAgent": request.headers.get("user-agent", ""),
            "path": safe_path(request.url.path),
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
            principal = getattr(request.state, "principal", None)
            if principal:
                actor, actor_role = principal.login, principal.role.value
            duration = round((time.perf_counter() - started) * 1000, 1)
            quiet = request.url.path.startswith(QUIET_PATHS)
            log.log(
                logging.DEBUG if (quiet and status < 400) else
                logging.WARNING if status >= 400 else logging.INFO,
                "%s %s → %s", request.method, safe_path(request.url.path), status,
                extra={
                    "event": "http.request",
                    "requestId": request_id,
                    "method": request.method,
                    "path": safe_path(request.url.path),
                    "query": safe_query(request),
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
                    "referer": safe_referer(request.headers.get("referer", "")),
                },
            )
            current_request_id.reset(token)
            security_context.reset(ctx_token)
