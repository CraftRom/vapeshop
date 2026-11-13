"""Offline PDF contract QA for all private chat uploads and downloads.

Run: PYTHONPATH=backend python backend/qa/qa_chat_pdf.py
Requires fastapi/starlette only; no bot token, network or live database.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
import sys

try:
    import aiogram.types
except ImportError:
    aiogram = ModuleType('aiogram')
    aiogram.__path__ = []
    types = ModuleType('aiogram.types')
    class BufferedInputFile:
        def __init__(self, data, filename):
            self.data, self.filename = data, filename
    types.BufferedInputFile = BufferedInputFile
    aiogram.types = types
    sys.modules.setdefault('aiogram', aiogram)
    sys.modules['aiogram.types'] = types

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from api.chat_media import (
    PDF_LIMIT, DOWNLOAD_LIMIT, pdf_signature, read_chat_upload,
    send_pdf_to_client, telegram_chat_file_response,
)

# Use an actual rendered, one-page QA PDF. No external server or client data.
PDF = (Path(__file__).resolve().parents[2] / 'qa/fixtures/chat-pdf.pdf').read_bytes()


def upload(blob=PDF, mime='application/pdf', name='receipt.pdf'):
    return UploadFile(filename=name, file=BytesIO(blob), headers=Headers({'content-type': mime}))


class Bot:
    def __init__(self, payload=PDF, fail=False):
        self.payload, self.fail = payload, fail
        self.calls = []
    async def send_document(self, chat_id, file, **options):
        self.calls.append((chat_id, file.filename, options))
        if self.fail:
            raise RuntimeError('upstream')
        return SimpleNamespace(document=SimpleNamespace(file_id='file-private'), message_id=42)
    async def get_file(self, file_id):
        return SimpleNamespace(file_size=len(self.payload), file_path='secret/file')
    async def download_file(self, file_path):
        return BytesIO(self.payload)


class PdfUploadTest(IsolatedAsyncioTestCase):
    async def test_mime_normal(self):
        blob, kind, mime, filename = await read_chat_upload(upload())
        self.assertEqual((blob, kind, mime, filename), (PDF, 'document', 'application/pdf', 'receipt.pdf'))

    async def test_extension_fallback_and_filename(self):
        _, kind, mime, filename = await read_chat_upload(upload(mime='application/octet-stream', name='../../invoice.pdf'))
        self.assertEqual((kind, mime, filename), ('document', 'application/pdf', 'invoice.pdf'))

    async def test_no_extension_with_pdf_mime(self):
        _, kind, mime, filename = await read_chat_upload(upload(name='invoice'))
        self.assertEqual((kind, mime, filename), ('document', 'application/pdf', 'invoice.pdf'))

    async def test_bad_signature_and_eof(self):
        for blob in (b'', b'<html>hello</html>', b'%PDF-1.7\nnotfinished', b'%PDF-3.0\n%%EOF'):
            with self.subTest(blob=blob[:20]), self.assertRaises(HTTPException) as failure:
                await read_chat_upload(upload(blob=blob))
            self.assertEqual(failure.exception.status_code, 422)
        self.assertFalse(pdf_signature(b'%PDF-1.4'))

    async def test_limit(self):
        with self.assertRaises(HTTPException) as failure:
            await read_chat_upload(upload(blob=PDF + b'x' * (PDF_LIMIT + 1 - len(PDF))))
        self.assertEqual(failure.exception.status_code, 413)

    async def test_send_to_customer(self):
        bot = Bot()
        attachment, sent = await send_pdf_to_client(bot, 12345, upload(), 'Document')
        self.assertEqual(attachment, {'file_id': 'file-private', 'file_kind': 'document', 'file_name': 'receipt.pdf'})
        self.assertEqual(sent.message_id, 42)
        self.assertEqual(bot.calls[0][0], 12345)
        self.assertTrue(bot.calls[0][2]['disable_content_type_detection'])

    async def test_no_untrusted_upload_to_customer(self):
        bot = Bot()
        with self.assertRaises(HTTPException) as failure:
            await send_pdf_to_client(bot, 12345, upload(b'nope'), 'Document')
        self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(bot.calls, [])

    async def test_no_video_through_pdf_route(self):
        bot = Bot()
        mp4 = (24).to_bytes(4,'big') + b'ftypisom\x00\x00\x02\x00isommp41'
        with self.assertRaises(HTTPException) as failure:
            await send_pdf_to_client(bot, 12345, upload(mp4, 'video/mp4', 'a.mp4'), 'Document')
        self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(bot.calls, [])

    async def test_delivery_failure(self):
        with self.assertRaises(HTTPException) as failure:
            await send_pdf_to_client(Bot(fail=True), 12345, upload(), 'Document')
        self.assertEqual(failure.exception.status_code, 502)


class PdfProxyTest(IsolatedAsyncioTestCase):
    async def test_private_pdf_response(self):
        message = SimpleNamespace(file_kind='document', file_name='receipt.pdf', file_id='secret')
        res = await telegram_chat_file_response(Bot(), message)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.media_type, 'application/pdf')
        self.assertTrue(res.headers['content-disposition'].startswith('attachment;'))
        self.assertEqual(res.headers['cache-control'], 'private, no-store')
        self.assertEqual(res.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(res.body, PDF)
        self.assertNotIn('secret', str(res.headers))

    async def test_fake_pdf_is_never_previewed(self):
        message = SimpleNamespace(file_kind='document', file_name='receipt.pdf', file_id='secret')
        with self.assertRaises(HTTPException) as failure:
            await telegram_chat_file_response(Bot(b'<script>x</script>'), message)
        self.assertEqual(failure.exception.status_code, 422)

    async def test_non_pdf_document_still_downloads(self):
        message = SimpleNamespace(file_kind='document', file_name='receipt.txt', file_id='secret')
        res = await telegram_chat_file_response(Bot(b'hello'), message)
        self.assertEqual(res.media_type, 'application/octet-stream')
        self.assertTrue(res.headers['content-disposition'].startswith('attachment;'))

    async def test_no_file(self):
        with self.assertRaises(HTTPException) as failure:
            await telegram_chat_file_response(Bot(), SimpleNamespace(file_id=None))
        self.assertEqual(failure.exception.status_code, 410)

    async def test_oversized_download(self):
        # Telegram Bot API's hosted getFile path cannot download >20 MiB.
        with self.assertRaises(HTTPException) as failure:
            await telegram_chat_file_response(Bot(PDF + b'z' * DOWNLOAD_LIMIT), SimpleNamespace(file_id='id', file_kind='document', file_name='receipt.pdf'))
        self.assertEqual(failure.exception.status_code, 413)


if __name__ == '__main__':
    main(verbosity=2)
