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

log = logging.getLogger("api.request")

# Доступний з будь-якого місця обробки запиту — щоб прикладні події
# (створено замовлення, невдалий вхід) можна було зв'язати з запитом,
# який їх спричинив.
current_request_id: ContextVar[str] = ContextVar("request_id", default="")

# Шляхи, які смикають моніторинг і планувальник. Пишемо їх на DEBUG:
# інакше вони витіснять із журналу все живе.
QUIET_PATHS = ("/api/health", "/api/debug/")


def client_ip(request: Request) -> str:
    """IP клієнта з урахуванням проксі.

    За nginx усі запити приходять з адреси контейнера, тому справжня
    адреса — у X-Forwarded-For, перша в ланцюжку.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = current_request_id.set(request_id)
        started = time.perf_counter()

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
                    "userAgent": request.headers.get("user-agent", ""),
                    "status": status,
                    "durationMs": duration,
                },
            )
            current_request_id.reset(token)
