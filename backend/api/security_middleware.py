"""Body budgets and response headers, including chunked request bodies."""
import re
import asyncio
import tempfile
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app
        self.upload_slots = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        if scope["type"] == "http" and headers.get(b"content-type", b"").startswith(b"multipart/"):
            async with self.upload_slots:
                return await self._handle(scope, receive, send)
        return await self._handle(scope, receive, send)

    async def _handle(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        headers = dict(scope.get("headers", []))
        from api.input_security import check_url, credentials_body, check_credentials_json
        def reject(detail, status=400):
            from shop import security_log
            security_log.record('security.input.rejected', reason=detail,
                                method=scope.get('method', ''))
            return JSONResponse({'detail': detail}, status, headers={
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer'})
        try:
            check_url(path, scope.get('query_string', b''), scope.get('method', ''))
        except (ValueError, UnicodeError) as exc:
            return await reject(str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError)
                                else 'Некоректний шлях запиту')(scope, receive, send)
        # User-level mutation budgets apply even when a trusted proxy's IP
        # limits are bypassed by an internal client. Auth/ownership remain
        # enforced by the endpoint; this guard only throttles *valid* tokens.
        if path.startswith('/api/shop/') and scope.get('method') in ('POST', 'PUT', 'PATCH', 'DELETE'):
            from api.shop_rate_limit import check_signed_write
            init_header = headers.get(b'x-telegram-init-data', b'')
            if len(init_header) <= 16384:
                allowed = await check_signed_write(path, scope.get('method', ''),
                                                  init_header.decode('utf-8', errors='replace'))
                if not allowed:
                    return await JSONResponse(
                        {'detail': 'Забагато дій за короткий час. Повторіть через хвилину.'},
                        429, headers={'Retry-After': '60', 'Cache-Control': 'no-store'},
                    )(scope, receive, send)
        credential_body = credentials_body(path, scope.get('method', ''))
        if credential_body:
            content_type = headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower()
            if content_type != b'application/json' and not (content_type.startswith(b'application/') and content_type.endswith(b'+json')):
                return await reject('Облікові дані приймаються лише як JSON', 415)(scope, receive, send)
        limit = 512 * 1024
        if credential_body:
            limit = 16 * 1024
        elif path == "/api/shop/client-log":
            limit = 16 * 1024
        elif path.startswith(("/api/telegram/", "/api/integrations/salesdrive/webhook/")):
            limit = 256 * 1024
        elif path == "/api/media" or re.fullmatch(r"/api/shop/orders/[0-9]+/chat/photo", path) or path in ("/api/catalog/product-transfer", "/api/catalog/products/import", "/api/catalog/product-transfer/import"):
            limit = 11 * 1024 * 1024
        elif path == "/api/backups/upload":
            limit = 201 * 1024 * 1024
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse({"detail": "Некоректний Content-Length"}, 400)(scope, receive, send)
        if declared > limit:
            return await JSONResponse({"detail": "Запит перевищує дозволений розмір"}, 413)(scope, receive, send)
        # Authenticate multipart before reading or spooling its body. Customer uploads
        # use signed Telegram data; dashboard writes also validate session/CSRF/role.
        if scope.get("method") in ("POST", "PUT", "PATCH") and headers.get(b"content-type", b"").startswith(b"multipart/"):
            from fastapi import HTTPException
            from fastapi.security import HTTPBearer
            from starlette.requests import Request
            from shop.repo.factory import get_repo
            from api.auth import _request_principal
            request = Request(scope)
            dependency = scope["app"].dependency_overrides.get(get_repo, get_repo)
            generator = dependency()
            try:
                repo = await generator.__anext__()
                creds = await HTTPBearer(auto_error=False)(request)
                if re.fullmatch(r"/api/shop/orders/[0-9]+/chat/photo", path):
                    from api.webapp_auth import require_webapp_user
                    await require_webapp_user(request.headers.get("x-telegram-init-data", ""), repo)
                elif path == "/api/backups/upload":
                    from api.auth import require_sysadmin
                    await require_sysadmin(request, creds, repo)
                else:
                    await _request_principal(request, creds, repo)
            except HTTPException as exc:
                return await JSONResponse({"detail": exc.detail}, exc.status_code)(scope, receive, send)
            finally:
                await generator.aclose()
        # Small JSON stays in memory; large backup bodies spool to the backup volume,
        # avoiding 200 MB of RAM per upload and the container's small /tmp budget.
        spool = None
        if path == "/api/backups/upload":
            from shop.paths import backups_dir
            spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, dir=backups_dir())
        messages, total = [], 0
        try:
            if scope.get("method") not in ("GET", "HEAD", "OPTIONS"):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body = message.get("body", b"")
                    total += len(body)
                    if total > limit:
                        return await JSONResponse({"detail": "Запит перевищує дозволений розмір"}, 413)(scope, receive, send)
                    if spool:
                        await run_in_threadpool(spool.write, body)
                    else:
                        messages.append(message)
                    if not message.get("more_body", False):
                        break
            if spool:
                await run_in_threadpool(spool.seek, 0)
            if credential_body:
                try:
                    check_credentials_json(b''.join(message.get('body', b'') for message in messages))
                except ValueError as exc:
                    return await reject(str(exc))(scope, receive, send)
            index, replayed = 0, 0
            async def bounded_receive():
                nonlocal index, replayed
                if spool and replayed < total:
                    chunk = await run_in_threadpool(spool.read, 65536)
                    replayed += len(chunk)
                    return {"type": "http.request", "body": chunk, "more_body": replayed < total}
                if index < len(messages):
                    message = messages[index]
                    index += 1
                    return message
                return await receive()
            async def protected_send(message):
                if message["type"] == "http.response.start" and path.startswith("/api/"):
                    response_headers = list(message.get("headers", []))
                    if path != "/api/landing-pages/public/render/page":
                        response_headers = [(k, v) for k, v in response_headers if k.lower() != b"cache-control"]
                        response_headers.append((b"cache-control", b"no-store"))
                    response_headers.extend([(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")])
                    message = {**message, "headers": response_headers}
                await send(message)
            await self.app(scope, bounded_receive, protected_send)
        finally:
            if spool:
                spool.close()


class SiteHostMiddleware:
    """Main app uses an explicit host allowlist; two public promo routes validate
    their dynamic host against published pages in the database inside the handler.
    Nginx exposes them only through an explicitly provisioned promo server_name.
    """
    PUBLIC_PROMO = {"/api/landing-pages/public/render/page", "/api/landing-pages/public/go/button"}

    def __init__(self, app, allowed_hosts):
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        self.app = app
        self.checked = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts, www_redirect=False)

    async def __call__(self, scope, receive, send):
        if scope.get("path") in self.PUBLIC_PROMO and scope.get("method") in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        return await self.checked(scope, receive, send)
