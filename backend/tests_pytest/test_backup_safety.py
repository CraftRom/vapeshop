"""Backup failures never publish a ready file or silently restore a live shop."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock
import stat

import pytest
from fastapi import HTTPException
from shop import backup_files as files
from api.routers import backups
from scheduler import tasks

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = SimpleNamespace(postgres_host='db', postgres_port=5432, postgres_user='elfar',
                           postgres_db='elfar', postgres_password='private-dummy')


def fake_dump(monkeypatch, *, failure=None, invalid=False):
    calls = []
    def run(command, **options):
        calls.append((command, options))
        if command[0] == 'pg_dump':
            Path(command[command.index('-f') + 1]).write_bytes(b'PGDMP' + b'x' * 1200)
            if failure == 'timeout':
                raise subprocess.TimeoutExpired(command, 1)
            return SimpleNamespace(returncode=1 if failure else 0)
        return SimpleNamespace(returncode=1 if invalid else 0)
    monkeypatch.setattr(files.subprocess, 'run', run)
    return calls


@pytest.mark.parametrize('failure', ['exit', 'timeout'])
def test_failed_dump_has_no_ready_or_partial_file(tmp_path, monkeypatch, failure):
    fake_dump(monkeypatch, failure=failure)
    with pytest.raises(files.BackupError):
        files.create_backup(tmp_path, SETTINGS)
    assert list(tmp_path.glob('*.dump')) == []
    assert list(tmp_path.glob('*.partial')) == []


def test_invalid_archive_does_not_become_ready(tmp_path, monkeypatch):
    fake_dump(monkeypatch, invalid=True)
    with pytest.raises(files.BackupError):
        files.create_backup(tmp_path, SETTINGS)
    assert not list(tmp_path.glob('*.dump'))


def test_new_files_are_private_unique_and_validated(tmp_path, monkeypatch):
    calls = fake_dump(monkeypatch)
    one = files.create_backup(tmp_path, SETTINGS)
    two = files.create_backup(tmp_path, SETTINGS)
    assert one != two and one.read_bytes() == two.read_bytes()
    assert stat.S_IMODE(one.stat().st_mode) == 0o600
    assert len([c for c, _ in calls if c[0] == 'pg_restore']) == 2
    for command, options in calls:
        assert 'private-dummy' not in command


def test_same_volume_lock_blocks_a_second_writer(tmp_path, monkeypatch):
    calls = fake_dump(monkeypatch)
    with files.backup_lock(tmp_path):
        with pytest.raises(files.BackupBusy):
            files.create_backup(tmp_path, SETTINGS)
    assert not calls


def test_publish_never_overwrites_an_existing_copy(tmp_path):
    target = tmp_path / 'old.dump'; target.write_bytes(b'old')
    with files.staging_file(tmp_path) as temporary:
        temporary.write_bytes(b'new')
        with pytest.raises(FileExistsError):
            files.publish(temporary, target)
    assert target.read_bytes() == b'old'


def test_daily_copy_is_validated_and_not_duplicated(tmp_path, monkeypatch):
    calls = fake_dump(monkeypatch)
    one = files.create_backup(tmp_path, SETTINGS, daily='2026-11-16')
    two = files.create_backup(tmp_path, SETTINGS, daily='2026-11-16')
    assert one == two
    assert len([c for c, _ in calls if c[0] == 'pg_dump']) == 1


def test_old_incomplete_daily_dump_is_quarantined(tmp_path, monkeypatch):
    old = tmp_path / 'elfar-2026-11-16.dump'; old.write_bytes(b'broken')
    fake_dump(monkeypatch)
    result = files.create_backup(tmp_path, SETTINGS, daily='2026-11-16')
    assert result.name.startswith('elfar-auto-2026-11-16-')
    assert not old.exists()
    assert len(list(tmp_path.glob('*.invalid-*'))) == 1


@pytest.mark.asyncio
async def test_database_backup_switch_overrides_environment(tmp_path, monkeypatch):
    @asynccontextmanager
    async def repo():
        yield SimpleNamespace()
    monkeypatch.setattr(tasks, 'open_repo', repo)
    monkeypatch.setattr(tasks, 'get_shop_settings', AsyncMock(return_value=SimpleNamespace(backup_enabled=False)))
    monkeypatch.setattr(tasks.settings, 'backup_enabled', True)
    monkeypatch.setattr(tasks, '_backup_dir', lambda: tmp_path)
    mock = AsyncMock()
    monkeypatch.setattr('starlette.concurrency.run_in_threadpool', mock)
    assert await tasks.run_backup_if_due({}) is False
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_enabled_database_switch_can_override_disabled_environment(tmp_path, monkeypatch):
    @asynccontextmanager
    async def repo():
        yield SimpleNamespace()
    monkeypatch.setattr(tasks, 'open_repo', repo)
    monkeypatch.setattr(tasks, 'get_shop_settings', AsyncMock(return_value=SimpleNamespace(
        backup_enabled=True, backup_hour=datetime.now(timezone.utc).hour, tz=timezone.utc)))
    monkeypatch.setattr(tasks.settings, 'backup_enabled', False)
    monkeypatch.setattr(tasks, '_backup_dir', lambda: tmp_path)
    file = tmp_path / 'valid.dump'; file.write_bytes(b'PGDMP')
    mock = AsyncMock(return_value=file)
    monkeypatch.setattr('starlette.concurrency.run_in_threadpool', mock)
    state = {}
    assert await tasks.run_backup_if_due(state) is True
    assert state['last_backup_date'] == datetime.now(timezone.utc).date()
    assert await tasks.run_backup_if_due(state) is False
    assert mock.await_count == 1


@pytest.mark.asyncio
async def test_scheduler_failure_remains_retryable(tmp_path, monkeypatch):
    @asynccontextmanager
    async def repo():
        yield SimpleNamespace()
    monkeypatch.setattr(tasks, 'open_repo', repo)
    monkeypatch.setattr(tasks, 'get_shop_settings', AsyncMock(return_value=SimpleNamespace(
        backup_enabled=True, backup_hour=datetime.now(timezone.utc).hour, tz=timezone.utc)))
    monkeypatch.setattr(tasks, '_backup_dir', lambda: tmp_path)
    monkeypatch.setattr('starlette.concurrency.run_in_threadpool', AsyncMock(side_effect=files.BackupError('timeout')))
    state = {}
    assert await tasks.run_backup_if_due(state) is False
    assert 'last_backup_date' not in state


@pytest.mark.asyncio
async def test_old_browser_restore_cannot_execute_any_command(tmp_path, monkeypatch):
    source = tmp_path / 'source.dump'; source.write_bytes(b'PGDMP')
    monkeypatch.setattr(backups, 'backup_dir', lambda: tmp_path)
    calls = []
    monkeypatch.setattr(files.subprocess, 'run', lambda *a, **kw: calls.append(a))
    with pytest.raises(HTTPException) as error:
        await backups.restore(source.name, confirm=source.name, who=SimpleNamespace(login='audit'))
    assert error.value.status_code == 409
    assert source.read_bytes() == b'PGDMP' and not calls


@pytest.mark.asyncio
async def test_api_backup_does_not_block_the_event_loop(tmp_path, monkeypatch):
    import time
    from shop.services.backup_jobs import JobStore
    store = JobStore(tmp_path / 'jobs', tmp_path / 'backups')
    enqueue = store.enqueue
    def slow(*args):
        time.sleep(.12)
        return enqueue(*args)
    monkeypatch.setattr(store, 'enqueue', slow)
    monkeypatch.setattr(backups, 'configured_store', lambda: store)
    fired = []
    async def heartbeat():
        await asyncio.sleep(.02)
        fired.append('alive')
    operation = asyncio.create_task(backups.enqueue_job(backups.BackupJobIn(client_key='a'*32), who=SimpleNamespace(login='audit')))
    await heartbeat()
    assert fired and not operation.done()
    assert (await operation)['status'] == 'queued'


def test_retention_keeps_manual_uploaded_and_safety_files(tmp_path, monkeypatch):
    import os,time
    monkeypatch.setattr(tasks, '_backup_dir', lambda: tmp_path)
    names = ['elfar-2026-01-01.dump', 'elfar-auto-2026-01-01-time-random.dump',
             'elfar-manual-2026-01-01.dump', 'elfar-before-restore-20260101.dump',
             'elfar-manual-2026-01-02.dump', 'elfar-upload-2026-01-01.dump']
    for name in names:
        path = tmp_path/name;path.write_bytes(b'PGDMP');os.utime(path, (time.time()-86400*90,)*2)
    assert tasks.prune_backups(14) == 2
    assert sorted(path.name for path in tmp_path.glob('*.dump')) == sorted(names[2:])


@pytest.mark.asyncio
async def test_api_busy_response_does_not_queue_a_second_copy(tmp_path, monkeypatch):
    from shop.services.backup_jobs import JobStore
    store = JobStore(tmp_path / 'jobs', tmp_path / 'backups')
    monkeypatch.setattr(backups, 'configured_store', lambda: store)
    with files.backup_lock(store.directory), pytest.raises(HTTPException) as error:
        await backups.enqueue_job(backups.BackupJobIn(client_key='b'*32), who=SimpleNamespace(login='audit'))
    assert error.value.status_code == 409
    assert not store.recent()

