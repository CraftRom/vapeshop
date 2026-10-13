"""F04–F05: independent SQL sessions, crash windows and one-shot Telegram.

Run with PYTHONPATH=.:qa python qa/qa_broadcast_recovery.py.
Optional QA_BROADCAST_DATABASE_URL must point to a disposable *_broadcast_qa DB.
No Telegram request escapes this suite.
"""
from qa_paths import qa_db_path, qa_db_url
import asyncio
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta, timezone

DB = os.environ.get('QA_BROADCAST_DATABASE_URL', qa_db_url('qa_broadcast_recovery.db'))
if not DB.startswith('sqlite') and not DB.rsplit('/', 1)[-1].endswith('_broadcast_qa'):
    raise RuntimeError('Only a disposable *_broadcast_qa database is allowed')
if DB.startswith('sqlite'):
    Path(qa_db_path('qa_broadcast_recovery.db')).unlink(missing_ok=True)
os.environ.setdefault('TRUSTED_HOSTS','testserver,localhost,127.0.0.1')
os.environ.update(BOT_TOKEN='777001:TESTTOKEN', JWT_SECRET='t' * 32, DATABASE_URL=DB)

import httpx
from sqlalchemy import delete
from shop import models as m
from shop.db import engine
from shop.entities import BroadcastStatus as S
from shop.repo.factory import open_repo
from shop.services import broadcast as service
from shop.services.shop_settings import save_shop_settings
from shop.telegram import BroadcastDeliveryResult as Result, send_broadcast_once
from scheduler.tasks import run_due_broadcasts
from api.routers.broadcasts import send_broadcast, schedule_broadcast, unschedule_broadcast
from api.schemas import BroadcastOut, ScheduleIn
from fastapi import BackgroundTasks, HTTPException


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as c:
            await c.run_sync(m.Base.metadata.create_all)
            for table in (m.BroadcastDelivery, m.Broadcast, m.User):
                await c.execute(delete(table))
        async with open_repo() as r:
            await save_shop_settings(r, {'quiet_hours_enabled': False, 'broadcast_rate_per_second': 30})
            # Explicit rows avoid unrelated bot setup and expose deterministic cursor IDs.
            for uid in range(1, 5):
                r.s.add(m.User(id=uid, tg_id=1000 + uid, referral_code=f'QA{uid}', bot_reachable=True, age_confirmed=True))
            await r.s.commit()
        self.sender = AsyncMock(return_value=Result('sent'))
        self.mock = patch.object(service, 'send_broadcast_once', self.sender)
        self.mock.start()

    async def asyncTearDown(self):
        self.mock.stop()
        await engine.dispose()

    async def create(self, **values):
        async with open_repo() as r:
            return await r.create_broadcast({'title': 'QA', 'text': 'message', 'status': S.SENDING, **values})

    async def read(self, bid):
        async with open_repo() as r:
            return await r.get_broadcast(bid)

    async def expire(self, bid):
        async with open_repo() as r:
            await r.update_broadcast(bid, {'lease_until': datetime.now(timezone.utc) - timedelta(seconds=1)})

    async def claim(self, bid, owner='worker'):
        async with open_repo() as r:
            return await r.claim_broadcast(bid, owner)

    async def chunk(self, b, size=30):
        async with open_repo() as r:
            return await service.send_chunk(r, b, size)

    async def test_quiet_hours_hold_recovery_without_losing_progress(self):
        b = await self.create(cursor_id=2,sent_count=2)
        await self.claim(b.id)
        await self.expire(b.id)
        now = datetime.now(timezone.utc)
        async with open_repo() as r:
            await save_shop_settings(r, {'timezone': 'UTC', 'quiet_hours_enabled': True,
                'quiet_hours_start': now.hour, 'quiet_hours_end': (now.hour + 1) % 24})
        self.assertEqual(await run_due_broadcasts(),0)
        self.sender.assert_not_called()
        async with open_repo() as r:
            await save_shop_settings(r, {'quiet_hours_enabled': False})
        await run_due_broadcasts()
        self.assertEqual((await self.read(b.id)).sent_count,4)

    async def test_scheduler_processes_due_and_recovery_but_not_future_or_draft(self):
        past = await self.create(status=S.SCHEDULED, scheduled_at=datetime.now(timezone.utc)-timedelta(hours=1))
        pending = await self.create()
        future = await self.create(status=S.SCHEDULED, scheduled_at=datetime.now(timezone.utc)+timedelta(days=1))
        draft = await self.create(status=S.DRAFT)
        async with open_repo() as r:
            ids = {x.id for x in await r.due_broadcasts(datetime.now(timezone.utc))}
        self.assertEqual(ids,{past.id,pending.id})
        self.assertEqual(await run_due_broadcasts(),2)
        self.assertEqual((await self.read(future.id)).status,S.SCHEDULED)
        self.assertEqual((await self.read(draft.id)).status,S.DRAFT)

    async def test_atomic_claim_independent_sessions(self):
        b = await self.create()
        results = await asyncio.gather(self.claim(b.id, 'one'), self.claim(b.id, 'two'))
        self.assertEqual(sum(x is not None for x in results), 1)

    async def test_two_chunks_deliver_each_customer_once(self):
        b = await self.create()
        results = await asyncio.gather(self.chunk(b), self.chunk(b))
        self.assertEqual(sum(n for n, _ in results), 4)
        self.assertEqual(sorted(c.args[0] for c in self.sender.call_args_list), [1001,1002,1003,1004])
        row = await self.read(b.id)
        self.assertEqual((row.sent_count, row.failed_count, row.unknown_count, row.status), (4,0,0,S.SENT))

    async def test_stale_cursor_object_does_not_replay(self):
        b = await self.create()
        await self.chunk(b, 2)
        stale = type(b)(id=b.id, title='stale', text='stale', cursor_id=0)
        await self.chunk(stale, 30)
        self.assertEqual(len(self.sender.call_args_list), 4)
        self.assertTrue(all(c.args[1] == 'message' for c in self.sender.call_args_list))

    async def test_scheduler_recovers_legacy_sending_cursor(self):
        b = await self.create(cursor_id=2, sent_count=2)
        self.assertEqual(await run_due_broadcasts(), 1)
        self.assertEqual(sorted(c.args[0] for c in self.sender.call_args_list), [1003,1004])
        self.assertEqual((await self.read(b.id)).sent_count, 4)

    async def test_active_lease_is_not_recovered(self):
        b = await self.create()
        await self.claim(b.id)
        self.assertEqual(await run_due_broadcasts(), 0)
        self.sender.assert_not_called()

    async def test_crash_after_network_before_result_is_unknown(self):
        b = await self.create()
        async def crash(*args):
            raise asyncio.CancelledError()
        self.sender.side_effect = crash
        with self.assertRaises(asyncio.CancelledError):
            await self.chunk(b, 1)
        self.sender.side_effect = None
        await self.expire(b.id)
        await run_due_broadcasts()
        row = await self.read(b.id)
        self.assertEqual((row.sent_count, row.unknown_count, row.status), (3,1,S.SENT))
        self.assertEqual(sum(c.args[0] == 1001 for c in self.sender.call_args_list), 1)
        async with open_repo() as r:
            self.assertEqual((await r.list_broadcast_deliveries(b.id))['items'][0]['status'], 'unknown')

    async def test_crash_after_saved_delivery_before_cursor_does_not_replay(self):
        b = await self.create()
        await self.claim(b.id)
        async with open_repo() as r:
            await r.begin_broadcast_delivery(b.id,'worker',1,1001)
            await r.finish_broadcast_delivery(b.id,'worker',1,'sent')
        await self.expire(b.id)
        await run_due_broadcasts()
        self.assertEqual(sorted(c.args[0] for c in self.sender.call_args_list), [1002,1003,1004])
        self.assertEqual((await self.read(b.id)).sent_count, 4)

    async def test_fencing_rejects_late_result_heartbeat_and_release(self):
        b = await self.create()
        await self.claim(b.id, 'old')
        async with open_repo() as r:
            await r.begin_broadcast_delivery(b.id,'old',1,1001)
        await self.expire(b.id)
        await self.claim(b.id, 'new')
        async with open_repo() as r:
            self.assertFalse(await r.finish_broadcast_delivery(b.id,'old',1,'sent'))
            self.assertFalse(await r.heartbeat_broadcast(b.id,'old'))
            self.assertFalse(await r.release_broadcast(b.id,'old',finished=True))
        row = await self.read(b.id)
        self.assertEqual((row.sent_count,row.unknown_count,row.lease_owner), (0,1,'new'))

    async def test_old_owner_cannot_start_after_recovery(self):
        b = await self.create()
        await self.claim(b.id,'old')
        await self.expire(b.id)
        await self.claim(b.id,'new')
        async with open_repo() as r:
            self.assertEqual((await r.begin_broadcast_delivery(b.id,'old',1,1001))['action'],'lost')

    async def test_expired_owner_cannot_start_network_attempt(self):
        b = await self.create()
        await self.claim(b.id)
        await self.expire(b.id)
        async with open_repo() as r:
            self.assertEqual((await r.begin_broadcast_delivery(b.id,'worker',1,1001))['action'], 'lost')

    async def test_result_commit_counts_only_once(self):
        b = await self.create()
        await self.claim(b.id)
        async with open_repo() as r:
            await r.begin_broadcast_delivery(b.id,'worker',1,1001)
            self.assertTrue(await r.finish_broadcast_delivery(b.id,'worker',1,'sent'))
            self.assertFalse(await r.finish_broadcast_delivery(b.id,'worker',1,'sent'))
        self.assertEqual((await self.read(b.id)).sent_count, 1)

    async def test_heartbeat_renews_during_slow_network(self):
        b = await self.create()
        entered = asyncio.Event()
        async def slow(*args):
            entered.set()
            await asyncio.sleep(.35)
            return Result('sent')
        self.sender.side_effect = slow
        with patch.object(service, 'HEARTBEAT_SECONDS', .05):
            worker = asyncio.create_task(self.chunk(b, 1))
            await asyncio.wait_for(entered.wait(), 5)
            before = (await self.read(b.id)).heartbeat_at
            await asyncio.sleep(.18)
            after = (await self.read(b.id)).heartbeat_at
            self.assertGreater(after, before)
            self.assertEqual(await self.chunk(b), (0,False))
            await worker

    async def test_safe_retry_persists_attempt_and_waits_due_time(self):
        b = await self.create()
        self.sender.return_value = Result('retry', 'Too Many Requests', 3600)
        await self.chunk(b, 1)
        row = await self.read(b.id)
        self.assertEqual((row.cursor_id,row.sent_count,row.failed_count), (0,0,0))
        self.assertEqual(await run_due_broadcasts(), 0)
        self.assertEqual(self.sender.call_count, 1)
        await self.expire(b.id)
        # Lease expiry alone must not bypass the recipient retry_after.
        await self.chunk(b, 1)
        self.assertEqual(self.sender.call_count, 1)
        async with open_repo() as r:
            d = await r.s.get(m.BroadcastDelivery,(b.id,1))
            d.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await r.s.commit()
        await self.expire(b.id)
        self.sender.return_value = Result('sent')
        await service.run_to_completion(b.id, 30)
        self.assertEqual((await self.read(b.id)).sent_count, 4)
        async with open_repo() as r:
            self.assertEqual((await r.list_broadcast_deliveries(b.id))['items'][0]['attempts'],2)

    async def test_retry_attempts_are_bounded(self):
        b = await self.create()
        self.sender.return_value = Result('retry','connect failed',0)
        for _ in range(3):
            await self.chunk(b, 1)
        self.assertEqual((await self.read(b.id)).failed_count, 1)
        self.assertEqual(self.sender.call_count,3)

    async def test_definite_failure_and_ambiguous_result_are_separate(self):
        b = await self.create()
        self.sender.side_effect = [Result('failed','Forbidden'), Result('unknown','timeout'), Result('sent'), Result('sent')]
        await self.chunk(b)
        row = await self.read(b.id)
        self.assertEqual((row.sent_count,row.failed_count,row.unknown_count), (2,1,1))
        await self.chunk(b)
        self.assertEqual(self.sender.call_count,4)

    async def test_worker_exception_keeps_recoverable_state(self):
        b = await self.create()
        self.sender.side_effect = RuntimeError('mock failure')
        self.assertEqual(await self.chunk(b,1),(0,False))
        row = await self.read(b.id)
        self.assertEqual(row.status,S.SENDING)
        self.assertIsNotNone(row.last_error)
        self.sender.side_effect = None
        await self.expire(b.id)
        await run_due_broadcasts()
        row = await self.read(b.id)
        self.assertEqual((row.sent_count,row.unknown_count),(3,1))

    async def test_api_send_race_enqueues_once(self):
        b = await self.create(status=S.DRAFT)
        async def send():
            async with open_repo() as r:
                background = BackgroundTasks()
                try:
                    await send_broadcast(b.id, background, r)
                    return len(background.tasks)
                except HTTPException as exc:
                    return exc.status_code
        self.assertEqual(sorted(await asyncio.gather(send(),send())),[1,409])
        self.sender.assert_not_called()
        # Simulate API dying before its background task starts.
        await run_due_broadcasts()
        self.assertEqual((await self.read(b.id)).sent_count,4)

    async def test_failed_resume_preserves_counts_and_cursor(self):
        b = await self.create(status=S.FAILED,cursor_id=2,sent_count=2)
        async with open_repo() as r:
            bg = BackgroundTasks()
            await send_broadcast(b.id,bg,r)
        await run_due_broadcasts()
        self.assertEqual((await self.read(b.id)).sent_count,4)
        self.assertEqual(self.sender.call_count,2)

    async def test_schedule_unschedule_and_delete_cannot_override_claim(self):
        b = await self.create(status=S.SCHEDULED,scheduled_at=datetime.now(timezone.utc)-timedelta(hours=1))
        await self.claim(b.id)
        async with open_repo() as r:
            with self.assertRaises(HTTPException):
                await unschedule_broadcast(b.id,r)
            with self.assertRaises(HTTPException):
                await schedule_broadcast(b.id,ScheduleIn(scheduled_at=datetime.now(timezone.utc)+timedelta(hours=1)),r)
            self.assertFalse(await r.delete_broadcast(b.id))
        self.assertEqual((await self.read(b.id)).status,S.SENDING)

    async def test_journal_http_contract_is_staff_only_and_validates_pagination(self):
        from api.main import app
        from api.auth import require_staff
        b = await self.create()
        await self.chunk(b)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            self.assertEqual((await client.get(f'/api/broadcasts/{b.id}/deliveries')).status_code,401)
            app.dependency_overrides[require_staff] = lambda: None
            try:
                response = await client.get(f'/api/broadcasts/{b.id}/deliveries?limit=2')
                self.assertEqual(response.status_code,200)
                self.assertEqual(len(response.json()['items']),2)
                self.assertEqual(response.json()['next_cursor'],2)
                self.assertEqual((await client.get(f'/api/broadcasts/{b.id}/deliveries?limit=201')).status_code,422)
                self.assertEqual((await client.get('/api/broadcasts/99999/deliveries')).status_code,404)
            finally:
                app.dependency_overrides.pop(require_staff,None)

    async def test_journal_pagination_and_delete(self):
        b = await self.create()
        await self.chunk(b)
        async with open_repo() as r:
            one = await r.list_broadcast_deliveries(b.id,0,2)
            two = await r.list_broadcast_deliveries(b.id,one['next_cursor'],2)
            self.assertEqual([x['user_id'] for x in one['items']+two['items']], [1,2,3,4])
            self.assertIsNone(two['next_cursor'])
            out = BroadcastOut.model_validate(await r.get_broadcast(b.id)).model_dump()
            self.assertNotIn('lease_owner',out)
            self.assertTrue(await r.delete_broadcast(b.id))
            self.assertEqual((await r.list_broadcast_deliveries(b.id))['items'],[])


class TelegramTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, response=None, error=None, **kw):
        client = AsyncMock()
        client.post = AsyncMock(side_effect=error,return_value=response)
        with patch('shop.telegram.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            result = await send_broadcast_once(1001,'text',**kw)
        self.assertEqual(client.post.call_count,1)
        return result, client.post.call_args.kwargs['json']

    async def test_ok_and_canonical_photo_button(self):
        result,payload = await self.call(httpx.Response(200,json={'ok':True}),photo_url='https://example.org/p.jpg',button_text='Shop',button_url='https://www.elfar.pp.ua/app/')
        self.assertEqual(result.status,'sent')
        self.assertIn('photo',payload)
        self.assertEqual(payload['reply_markup']['inline_keyboard'][0][0]['url'],'https://elfar.pp.ua/app/')

    async def test_429_honors_full_retry_after(self):
        result,_ = await self.call(httpx.Response(429,json={'ok':False,'error_code':429,'parameters':{'retry_after':120},'description':'flood'}))
        self.assertEqual((result.status,result.retry_after),('retry',120))

    async def test_403_is_terminal(self):
        result,_ = await self.call(httpx.Response(403,json={'ok':False,'error_code':403,'description':'blocked'}))
        self.assertEqual(result.status,'failed')

    async def test_timeout_never_retries_and_redacts_token(self):
        result,_ = await self.call(error=httpx.ReadTimeout('https://secret-bot-token/sendMessage'))
        self.assertEqual(result.status,'unknown')
        self.assertNotIn('secret-bot-token',result.error)

    async def test_connect_failure_is_safe_to_retry(self):
        result,_ = await self.call(error=httpx.ConnectError('unavailable'))
        self.assertEqual(result.status,'retry')

    async def test_invalid_response_and_gateway_failure_are_unknown(self):
        for response in (httpx.Response(200,text='bad'),httpx.Response(502,json={'ok':False,'description':'gateway'}),httpx.Response(200,json=[])):
            result,_ = await self.call(response)
            self.assertEqual(result.status,'unknown')


class MigrationTests(unittest.TestCase):
    def test_upgrade_preserves_old_cursor_and_enables_worker_stop_gate(self):
        import importlib.util
        import sqlalchemy as sa
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from shop.broadcast_upgrade import needs_worker_stop
        path = Path(__file__).resolve().parents[1] / 'alembic/versions/f6b3a8d21c90_broadcast_recovery.py'
        spec = importlib.util.spec_from_file_location('broadcast_migration',path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        local = sa.create_engine('sqlite:///:memory:')
        with local.begin() as c:
            self.assertFalse(needs_worker_stop(c))
            c.execute(sa.text('CREATE TABLE broadcasts (id INTEGER PRIMARY KEY, status VARCHAR(16), cursor_id INTEGER, sent_count INTEGER)'))
            c.execute(sa.text("INSERT INTO broadcasts VALUES (1, 'SENDING', 77, 70)"))
            self.assertTrue(needs_worker_stop(c))
            with Operations.context(MigrationContext.configure(c)):
                migration.upgrade()
            self.assertFalse(needs_worker_stop(c))
            row = c.execute(sa.text('SELECT cursor_id,sent_count,unknown_count,lease_owner FROM broadcasts')).one()
            self.assertEqual(tuple(row),(77,70,0,None))
            self.assertTrue(sa.inspect(c).has_table('broadcast_deliveries'))
            with Operations.context(MigrationContext.configure(c)):
                migration.downgrade()
            self.assertTrue(needs_worker_stop(c))
            self.assertFalse(sa.inspect(c).has_table('broadcast_deliveries'))
        local.dispose()

    def test_runtime_rollback_is_blocked_after_queue_upgrade(self):
        import subprocess
        deploy = (Path(__file__).resolve().parents[2]/'deploy/deploy.sh').read_text()
        function = deploy[deploy.index('rollback_core_runtime()'):deploy.index('echo "==> ФАЗА 1/6')]
        run = subprocess.run(['bash','-c', 'CATALOG_BREAKING_UPGRADE=0\nBROADCAST_QUEUE_UPGRADE=1\ndocker(){ echo UNEXPECTED_DOCKER; }\n'+function+'\nrollback_core_runtime'],capture_output=True,text=True)
        self.assertEqual(run.returncode,0)
        self.assertNotIn('UNEXPECTED_DOCKER',run.stdout+run.stderr)
        self.assertIn('автоматичний runtime rollback пропущено',run.stderr)

    def test_queue_upgrade_requires_backup_before_stopping_workers(self):
        import subprocess
        deploy = (Path(__file__).resolve().parents[2]/'deploy/deploy.sh').read_text()
        segment = deploy[deploy.index('BROADCAST_QUEUE_UPGRADE="$'):deploy.index('if ! "${COMPOSE[@]}" run --rm migrate')]
        fake = 'fake_compose(){ if [[ "$*" == *broadcast_upgrade* ]]; then echo 1; else echo "CALL $*" >&2; fi; }\nCOMPOSE=(fake_compose)\n'
        failed = subprocess.run(['bash','-c',fake+'BACKUP_CREATED=0\n'+segment],capture_output=True,text=True)
        self.assertEqual(failed.returncode,1)
        self.assertNotIn('CALL stop',failed.stderr)
        ready = subprocess.run(['bash','-c',fake+'BACKUP_CREATED=1\n'+segment],capture_output=True,text=True)
        self.assertEqual(ready.returncode,0,ready.stderr)
        self.assertIn('CALL stop api scheduler',ready.stderr)

    def test_postgres_migration_sql_and_single_alembic_head(self):
        from io import StringIO
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        backend = Path(__file__).resolve().parents[1]
        config = Config(str(backend / 'alembic.ini'))
        config.set_main_option('script_location',str(backend/'alembic'))
        script = ScriptDirectory.from_config(config)
        self.assertEqual(script.get_heads(),['f7d4b2c90a61'])
        # Compile revision DDL through the PostgreSQL dialect without a live server.
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        spec=importlib.util.spec_from_file_location('pg_broadcast_migration',backend/'alembic/versions/f6b3a8d21c90_broadcast_recovery.py')
        migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
        out=StringIO()
        with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':out})):
            migration.upgrade()
        sql=out.getvalue()
        self.assertIn('TIMESTAMP WITH TIME ZONE',sql)
        self.assertIn('PRIMARY KEY (broadcast_id, user_id)',sql)
        self.assertIn('ON DELETE CASCADE',sql)
        self.assertIn('ix_broadcasts_recovery',sql)


if __name__ == '__main__':
    unittest.main(verbosity=2)
