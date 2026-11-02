"""End-to-end API storage and Telegram wire contracts; no live recipients."""
import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image
from qa_common import Report, boot
from qa_paths import qa_db_path

storage = TemporaryDirectory(prefix='broadcast-media-qa-')
os.environ['ELFAR_DATA_ROOT'] = storage.name
app, Session, _ = boot(qa_db_path('broadcast_content.db'))
from shop import models
from shop.repo.sql import SqlRepository
from shop.telegram import send_broadcast_once
from shop.services.broadcast_content import local_media_name
from api.routers import media
from shop.services import broadcast as queue
r = Report('Broadcast content and media')

def image_bytes(fmt):
    output = BytesIO()
    Image.new('RGB', (32, 20), 'purple').save(output, format=fmt)
    return output.getvalue()

async def run():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        login = await client.post('/api/auth/login', json={'login': 'admin', 'password': 'secret'})
        admin = {'Authorization': 'Bearer '+login.json()['access_token']}
        base = dict(title='Повідомлення', text='Ціна < 100 & доставка > 0', text_format='plain')
        async def create(**updates):
            return await client.post('/api/broadcasts', headers=admin, json={**base, **updates})
        first = await create(client_key='qa-stable-create')
        r.check(first.status_code == 201 and first.json()['text'] == base['text'] and first.json()['text_format'] == 'plain', 'plain text preserves angle brackets and ampersands', first.text)
        bid = first.json()['id']
        replay = await create(client_key='qa-stable-create')
        r.check(replay.status_code == 201 and replay.json()['id'] == bid, 'repeated create uses the same ID')
        r.check(len((await client.get('/api/broadcasts', headers=admin)).json()) == 1, 'repeated create leaves no duplicate draft')
        for values in [dict(title='   '), dict(text='   '), dict(text='x'*4097), dict(text_format='html', text='<b>незакрито'), dict(text_format='html', text='<script>alert(1)</script>'), dict(text_format='html', text='<a href="javascript:alert(1)">click</a>'), dict(text_format='html', text='A & B'), dict(button_text='Кнопка'), dict(button_url='https://example.org'), dict(button_text='Go', button_url='javascript:alert(1)'), dict(photo_url='file:///etc/passwd'), dict(photo_url='/media/../secret.png'), dict(segment={'type':'inactive'}), dict(segment={'type':'unknown'})]:
            response = await create(**values)
            r.check(response.status_code == 422, f'invalid content rejected: {str(values)[:75]}', response.text)
        response = await create(text='x'*4096)
        r.check(response.status_code == 201, '4096 plain characters accepted without photo')
        response = await create(text_format='html', text='<b>'+'x'*4096+'</b>')
        r.check(response.status_code == 201, 'HTML length counts visible text')
        changed = await client.put(f'/api/broadcasts/{bid}', headers=admin, json={**base, 'text_format':'html', 'text':'<b>Новий текст</b>'})
        r.check(changed.status_code == 200 and changed.json()['text_format'] == 'html', 'draft edits preserve selected format')
        uploads = []
        for fmt in ['PNG','JPEG','WEBP','GIF']:
            raw = image_bytes(fmt)
            result = await client.post('/api/media', headers=admin, files={'file':('photo.'+fmt.lower(), raw)})
            r.check(result.status_code == 201, f'{fmt} upload accepted', result.text)
            url = result.json()['url']; uploads.append(url)
            response = await create(text='x'*1024, photo_url=url)
            r.check(response.status_code == 201, f'{fmt} image and caption saved')
            sender = AsyncMock()
            sender.post.return_value = httpx.Response(200, json={'ok':True})
            with patch('shop.telegram.httpx.AsyncClient') as factory:
                factory.return_value.__aenter__.return_value = sender
                delivery = await send_broadcast_once(123, base['text'], url, 'Магазин', 'https://www.elfar.pp.ua/app/', text_format='plain')
            args = sender.post.call_args
            r.check(delivery.status == 'sent' and sender.post.call_count == 1 and args.args[0].endswith('/sendPhoto'), f'{fmt} makes one photo request')
            fields, files = args.kwargs['data'], args.kwargs['files']
            jpeg = files['photo'][1]
            r.check(jpeg.startswith(b'\xff\xd8') and files['photo'][2] == 'image/jpeg' and fields['caption'] == base['text'] and 'parse_mode' not in fields, f'{fmt} uploaded as JPEG multipart with literal caption')
            r.check(json.loads(fields['reply_markup'])['inline_keyboard'][0][0]['url'] == 'https://elfar.pp.ua/app/', f'{fmt} multipart preserves canonical button')
        url = uploads[0]
        response = await create(text='x'*1025, photo_url=url)
        r.check(response.status_code == 422, '1025-character photo caption rejected before delivery')
        response = await create(text_format='html', text='<b>'+'x'*1024+'</b>', photo_url=url)
        r.check(response.status_code == 201, '1024 visible HTML characters accepted with photo')
        response = await create(photo_url='/media/missing.png')
        r.check(response.status_code == 422, 'missing local file rejected before draft creation')
        # An absolute URL to our own media also takes the multipart path.
        r.check(local_media_name('https://www.elfar.pp.ua'+url) == url.rsplit('/',1)[-1], 'own absolute media URLs resolved locally')
        r.check(local_media_name('https://foreign.example'+url) is None, 'foreign host cannot select local files')
        sender = AsyncMock(); sender.post.return_value = httpx.Response(200, json={'ok':True})
        with patch('shop.telegram.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = sender
            sent = await send_broadcast_once(123, base['text'], text_format='plain')
        body = sender.post.call_args.kwargs['json']
        r.check(sent.status == 'sent' and body['text'] == base['text'] and 'parse_mode' not in body and sender.post.call_args.args[0].endswith('/sendMessage'), 'plain message uses sendMessage without parse_mode')
        sender.reset_mock();sender.post.return_value=httpx.Response(200,json={'ok':True})
        with patch('shop.telegram.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = sender
            sent = await send_broadcast_once(123, '<b>HTML</b>', text_format='html')
        r.check(sent.status == 'sent' and sender.post.call_args.kwargs['json']['parse_mode'] == 'HTML', 'HTML mode stays explicit')
        sender.reset_mock();sender.post.side_effect=httpx.ReadTimeout('lost response')
        with patch('shop.telegram.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = sender
            sent = await send_broadcast_once(123, 'Текст', url, text_format='plain')
        r.check(sent.status == 'unknown' and sender.post.call_count == 1, 'ambiguous photo delivery is not repeated internally')
        sender.reset_mock()
        with patch('shop.telegram.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = sender
            sent = await send_broadcast_once(123, '<b>broken', text_format='html')
        r.check(sent.status == 'failed' and sender.post.call_count == 0, 'invalid HTML never reaches Telegram')
        with patch.object(queue, 'run_to_completion', new_callable=AsyncMock) as launch:
            response = await client.post(f'/api/broadcasts/{bid}/send', headers=admin)
            r.check(response.status_code == 200 and response.json()['status'] == 'sending' and launch.await_count == 1, 'launch queues validated draft once')
            response = await client.post(f'/api/broadcasts/{bid}/send', headers=admin)
            r.check(response.status_code == 409 and launch.await_count == 1, 'second launch does not enqueue again')
            replay = await create(client_key='qa-stable-create')
            r.check(replay.json()['id'] == bid and replay.json()['status'] == 'sending', 'create recovery exposes an already launched broadcast')
        response = await client.put(f'/api/broadcasts/{bid}', headers=admin, json=base)
        r.check(response.status_code == 409, 'active broadcast cannot be edited')
        response = await client.delete('/api/media/'+url.rsplit('/',1)[-1], headers=admin)
        r.check(response.status_code == 409, 'referenced campaign image cannot be deleted')
        response = await create(scheduled_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
        r.check(response.status_code == 422, 'past schedule rejected during creation')
        # Gallery search and pagination must include old images beyond the initial page.
        directory = media._media_dir()
        for index in range(30):
            (directory/f'gallery-{index:03d}.png').write_bytes(image_bytes('PNG'))
        listing = (await client.get('/api/media?limit=24', headers=admin)).json()
        r.check(len(listing['files']) == 24 and listing['has_more'], 'gallery exposes pagination')
        found = (await client.get('/api/media?search=gallery-000&limit=24', headers=admin)).json()
        r.check(found['total'] == 1 and found['files'][0]['name'] == 'gallery-000.png', 'gallery searches the entire storage')
        r.check((await client.get('/api/media?limit=501', headers=admin)).status_code == 422, 'gallery bounds page size')
        response = await client.delete('/api/media/gallery-000.png', headers=admin)
        r.check(response.status_code == 204, 'unused image can be removed')
        r.check((await client.post('/api/media', headers=admin, files={'file':('broken.png',b'bad')})).status_code == 415, 'corrupted uploads rejected')
    await Session.kw['bind'].dispose()

asyncio.run(run())
storage.cleanup()
raise SystemExit(bool(r.done()))
