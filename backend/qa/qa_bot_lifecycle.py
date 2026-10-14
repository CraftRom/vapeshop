"""Polling lifecycle: release real aiohttp sessions even before polling starts."""
import os

from qa_paths import QA_DATA_DIR, qa_db_url

os.environ.update(
    BOT_TOKEN="777001:TESTTOKEN", JWT_SECRET="t" * 32,
    DATABASE_URL=qa_db_url("bot_lifecycle.db"), REDIS_URL="",
    LOG_DIR=str(QA_DATA_DIR / "logs"),
)

import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from bot import __main__ as entry


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # A real allocated ClientSession proves that cleanup releases the resource.
        # All Telegram and database operations below are mocked; no network calls.
        self.session = AiohttpSession()
        self.client = await self.session.create_session()
        self.bot = NS(
            session=NS(close=AsyncMock(wraps=self.session.close)),
            get_me=AsyncMock(return_value=NS(username="qa_bot")),
            set_my_commands=AsyncMock(), delete_webhook=AsyncMock(),
        )
        self.dp = NS(start_polling=AsyncMock())
        repo = MagicMock()
        repo.__aenter__.return_value = NS()
        mocks = {
            "init_db": AsyncMock(), "build_bot": MagicMock(return_value=self.bot),
            "build_dispatcher": MagicMock(return_value=self.dp),
            "open_repo": MagicMock(return_value=repo),
            "get_shop_settings": AsyncMock(return_value=NS(public_url="https://shop.invalid")),
            "sync_menu": AsyncMock(return_value=True),
            "log": MagicMock(),
        }
        self.mocks = mocks
        self.patcher = patch.multiple(entry, **mocks)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.session.close()  # Cleanup if an assertion fails.

    def assert_released(self):
        self.bot.session.close.assert_awaited_once()
        self.assertTrue(self.client.closed)

    async def assert_failure(self, mock):
        failure = RuntimeError("simulated startup failure")
        mock.side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            await entry.main()
        self.assertIs(caught.exception, failure)
        self.assert_released()
        self.mocks["log"].exception.assert_called_once()
        self.assertEqual(
            self.mocks["log"].exception.call_args.kwargs["extra"]["event"],
            "bot.run.failed",
        )

    async def test_normal_stop_releases_session_and_keeps_pending_updates(self):
        await entry.main()
        self.assert_released()
        self.bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
        self.dp.start_polling.assert_awaited_once()
        call = self.dp.start_polling.call_args
        self.assertEqual(call.args, (self.bot,))
        self.assertFalse(call.kwargs["close_bot_session"])
        self.assertEqual(call.kwargs["polling_timeout"], 30)
        self.assertEqual(call.kwargs["backoff_config"].min_delay, 5)
        self.mocks["log"].exception.assert_not_called()

    async def test_real_dispatcher_shutdown_closes_storage_and_session_once(self):
        dp = Dispatcher()
        dp._polling = AsyncMock()  # End polling without contacting Telegram.
        dp.fsm.storage.close = AsyncMock(wraps=dp.fsm.storage.close)
        self.mocks["build_dispatcher"].return_value = dp
        await entry.main()
        dp.fsm.storage.close.assert_awaited_once()
        self.assert_released()

    async def test_get_me_failure_releases_session(self):
        await self.assert_failure(self.bot.get_me)
        self.mocks["build_dispatcher"].assert_not_called()

    async def test_commands_failure_releases_session(self):
        await self.assert_failure(self.bot.set_my_commands)
        self.dp.start_polling.assert_not_awaited()

    async def test_webhook_failure_releases_session(self):
        await self.assert_failure(self.bot.delete_webhook)
        self.mocks["build_dispatcher"].assert_not_called()

    async def test_dispatcher_construction_failure_releases_session(self):
        await self.assert_failure(self.mocks["build_dispatcher"])

    async def test_polling_failure_releases_session(self):
        await self.assert_failure(self.dp.start_polling)

    async def assert_cancelled(self, mock):
        entered = asyncio.Event()

        async def wait_forever(*args, **kwargs):
            entered.set()
            await asyncio.Future()

        mock.side_effect = wait_forever
        task = asyncio.create_task(entry.main())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assert_released()
            self.mocks["log"].exception.assert_not_called()
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def test_cancel_during_startup_releases_session(self):
        await self.assert_cancelled(self.bot.get_me)

    async def test_cancel_during_polling_releases_session(self):
        await self.assert_cancelled(self.dp.start_polling)

    async def test_menu_failure_does_not_prevent_polling(self):
        self.mocks["sync_menu"].side_effect = RuntimeError("menu unavailable")
        await entry.main()
        self.dp.start_polling.assert_awaited_once()
        self.assert_released()
        self.assertEqual(
            self.mocks["log"].exception.call_args.kwargs["extra"]["event"],
            "bot.menu_button.failed",
        )

    async def test_settings_failure_does_not_prevent_polling(self):
        self.mocks["get_shop_settings"].side_effect = RuntimeError("settings unavailable")
        await entry.main()
        self.dp.start_polling.assert_awaited_once()
        self.assert_released()


if __name__ == "__main__":
    unittest.main(verbosity=2)
