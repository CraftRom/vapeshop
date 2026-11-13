"""Small offline unit suite for bounded MP4 media and proxy response.

Run: PYTHONPATH=backend python -m unittest backend/qa/qa_chat_video.py
The full HTTP/Telegram/browser suites still require dependency installation.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from types import ModuleType, SimpleNamespace
import sys
import unittest

# Offline environments may lack aiogram; only the BufferedInputFile type
# is needed to import the self-contained media validation module.
try:
    import aiogram.types  # noqa: F401
except ImportError:
    aiogram = ModuleType('aiogram')
    aiogram.__path__ = []
    types = ModuleType('aiogram.types')
    class BufferedInputFile:  # pragma: no cover - package stub, no sends
        def __init__(self, data, filename):
            self.data, self.filename = data, filename
    types.BufferedInputFile = BufferedInputFile
    aiogram.types = types
    sys.modules['aiogram'] = aiogram
    sys.modules['aiogram.types'] = types

from fastapi import HTTPException, UploadFile
from api.chat_media import (
    VIDEO_LIMIT, DOWNLOAD_LIMIT, clean_filename, inline_mime,
    mp4_signature, read_chat_upload, telegram_chat_file_response,
)

MP4 = (24).to_bytes(4, 'big') + b'ftypisom\x00\x00\x02\x00isommp41'


def upload(data, mime='video/mp4', filename='video.mp4'):
    return UploadFile(filename=filename, file=BytesIO(data), headers={
        # Starlette reads file.content_type from Headers, not attrs.
        'content-type': mime,
    })


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_mp4(self):
        data, kind, mime, name = await read_chat_upload(upload(MP4, filename='video.mp4'))
        self.assertEqual((data, kind, mime, name), (MP4, 'video', 'video/mp4', 'video.mp4'))

    async def test_binary_mp4(self):
        data, kind, mime, name = await read_chat_upload(upload(MP4, 'application/octet-stream', 'clip.mp4'))
        self.assertEqual((kind, mime), ('video', 'video/mp4'))

    async def test_reject_false_mp4(self):
        for data in [b'<script>alert(1)</script>', b'not-mp4', b'', b'\x00'*30]:
            with self.subTest(data=data[:16]), self.assertRaises(HTTPException) as ctx:
                await read_chat_upload(upload(data))
            self.assertEqual(ctx.exception.status_code, 422)

    async def test_reject_bad_types(self):
        for kind in ['video/quicktime', 'video/webm', 'application/x-msdownload']:
            with self.subTest(kind=kind), self.assertRaises(HTTPException) as ctx:
                await read_chat_upload(upload(MP4, kind, 'file.mp4'))
            self.assertEqual(ctx.exception.status_code, 422)

    async def test_limit(self):
        with self.assertRaises(HTTPException) as ctx:
            await read_chat_upload(upload(MP4 + b'x'*(VIDEO_LIMIT+1-len(MP4))))
        self.assertEqual(ctx.exception.status_code, 413)

    async def test_bad_filename_cleaning(self):
        _, _, _, name = await read_chat_upload(upload(MP4, filename='../../foo/evil\\one.mp4'))
        self.assertEqual(name, 'one.mp4')
        self.assertEqual(clean_filename('a\r\n<b>.mp4', 'x'), 'ab.mp4')
        self.assertFalse(mp4_signature(b'x'*100))


class FileProxyTests(unittest.IsolatedAsyncioTestCase):
    class Bot:
        def __init__(self, size, payload=MP4, fail=False):
            self.size, self.payload, self.fail, self.downloads = size, payload, fail, 0
        async def get_file(self, file_id):
            if self.fail: raise RuntimeError('unavailable')
            return SimpleNamespace(file_size=self.size, file_path='private/path')
        async def download_file(self, path):
            self.downloads += 1
            return BytesIO(self.payload)

    async def test_video_proxy_private(self):
        bot = self.Bot(len(MP4))
        message = SimpleNamespace(file_id='private', file_kind='video', file_name='clip.mp4')
        response = await telegram_chat_file_response(bot, message)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, MP4)
        self.assertEqual(response.media_type, 'video/mp4')
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertNotIn('private', response.headers['content-disposition'])

    async def test_oversized_metadata_blocks_download(self):
        bot = self.Bot(DOWNLOAD_LIMIT + 1)
        with self.assertRaises(HTTPException) as ctx:
            await telegram_chat_file_response(bot, SimpleNamespace(file_id='id', file_kind='video', file_name='v.mp4'))
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertEqual(bot.downloads, 0)

    async def test_oversized_body_blocks_response(self):
        bot = self.Bot(None, b'0'*(DOWNLOAD_LIMIT+1))
        with self.assertRaises(HTTPException) as ctx:
            await telegram_chat_file_response(bot, SimpleNamespace(file_id='id', file_kind='video', file_name='v.mp4'))
        self.assertEqual(ctx.exception.status_code, 413)

    async def test_retention_and_failed_upstream(self):
        target = SimpleNamespace(file_id=None, file_kind='video', file_name='v.mp4')
        with self.assertRaises(HTTPException) as ctx:
            await telegram_chat_file_response(self.Bot(100), target)
        self.assertEqual(ctx.exception.status_code, 410)
        with self.assertRaises(HTTPException) as ctx:
            await telegram_chat_file_response(self.Bot(100, fail=True), SimpleNamespace(file_id='id', file_kind='video', file_name='v.mp4'))
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_doc_not_inline(self):
        target = SimpleNamespace(file_id='id', file_kind='document', file_name='danger.html')
        response = await telegram_chat_file_response(self.Bot(3, b'abc'), target)
        self.assertEqual(response.media_type, 'application/octet-stream')
        self.assertTrue(response.headers['content-disposition'].startswith('attachment;'))

    async def test_mime_from_telegram_filename(self):
        self.assertEqual(inline_mime('video', 'clip.webm'), 'video/webm')
        self.assertEqual(inline_mime('video', 'clip.mov'), 'video/quicktime')
        self.assertEqual(inline_mime('video', 'Відео'), 'video/mp4')


if __name__ == '__main__':
    unittest.main(verbosity=2)
