"""Body budgets include multipart overhead; normal JSON stays tightly bounded."""
from types import SimpleNamespace
import pytest
from api.security_middleware import SecurityMiddleware
from api.routers import backups
from starlette.datastructures import UploadFile
from io import BytesIO
from fastapi import HTTPException

MiB = 1024 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize('path,limit', [('/api/media', 9*MiB),
    ('/api/shop/orders/18/chat/photo', 9*MiB), ('/api/catalog/product-transfer/import', 11*MiB),
    ('/api/backups/upload', 201*MiB), ('/api/orders', 512*1024), ('/api/shop/client-log', 16*1024)])
async def test_declared_oversize_is_rejected_before_reading(path, limit):
    sent = []
    async def no_read(): pytest.fail('oversize body was read')
    async def app(*args): pytest.fail('oversize reached router')
    async def send(value): sent.append(value)
    scope = {'type':'http','path':path,'query_string':b'','method':'POST',
             'headers':[(b'content-length', str(limit+1).encode())]}
    await SecurityMiddleware(app)(scope, no_read, send)
    assert sent[0]['status'] == 413


@pytest.mark.asyncio
@pytest.mark.parametrize('declared', [False, True])
async def test_chunked_requests_cannot_bypass_the_budget(declared):
    sent = []
    scope = {'type':'http','path':'/api/media','query_string':b'','method':'POST',
             'headers':[(b'content-length',b'1')] if declared else []}
    count = 0
    async def receive():
        nonlocal count
        count += 1
        return {'type':'http.request','body':b'x'*MiB,'more_body': True}
    async def app(*args): pytest.fail('over budget request reached router')
    async def send(value): sent.append(value)
    await SecurityMiddleware(app)(scope, receive, send)
    assert sent[0]['status'] == 413 and count == 10


@pytest.mark.asyncio
async def test_backup_payload_limit_is_separate_from_multipart_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, 'backup_dir', lambda: tmp_path)
    monkeypatch.setattr(backups, 'MAX_UPLOAD', 10)
    with pytest.raises(HTTPException) as error:
        await backups.upload(UploadFile(filename='a.dump', file=BytesIO(b'PGDMP'+b'x'*6)),
                             who=SimpleNamespace(login='root'))
    assert error.value.status_code == 413
    assert not list(tmp_path.glob('*.dump')) and not list(tmp_path.glob('*.partial'))
