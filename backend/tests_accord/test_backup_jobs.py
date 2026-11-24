"""Persisted requests survive lost acknowledgements, worker crashes and retries."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from api.routers import backups
from shop import backup_files
from shop.services import backup_jobs as jobs


def store_at(root):
    return jobs.JobStore(root / 'jobs', root / 'backups')


def good_dump(directory, settings, *, output_name):
    with backup_files.backup_lock(directory), backup_files.staging_file(directory) as temporary:
        temporary.write_bytes(b'PGDMP valid fixture')
        return backup_files.publish(temporary, directory / output_name)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, 'create_backup', good_dump)
    monkeypatch.setattr(jobs, 'validate_dump', lambda p: None if p.read_bytes().startswith(b'PGDMP') else (_ for _ in ()).throw(backup_files.BackupError('invalid')))
    return store_at(tmp_path)


def test_same_request_and_active_job_are_deduplicated_across_reload(store, tmp_path):
    a = store.enqueue('a' * 32, 'root')
    assert store_at(tmp_path).enqueue('a' * 32, 'root') == a
    assert store.enqueue('b' * 32, 'root')['id'] == a['id']
    assert store.run_next(None)['status'] == 'succeeded'
    # The coalesced key remains mapped even after the first job finishes.
    assert store_at(tmp_path).enqueue('b' * 32, 'root')['id'] == a['id']
    assert len(store.recent()) == 1
    assert store.enqueue('c' * 32, 'root')['id'] != a['id']
    assert len(list(store.backups.glob('*.dump'))) == 1
    assert all((p.stat().st_mode & 0o777) == 0o600 for p in store.directory.glob('*.json'))


@pytest.mark.parametrize('moment', ['before_publish', 'after_publish'])
def test_actual_process_exit_is_recovered_without_duplicate_output(store, tmp_path, monkeypatch, moment):
    row = store.enqueue('d' * 32, 'root')
    def crash():
        def interrupted(*args, **kw):
            if moment == 'after_publish': good_dump(*args, **kw)
            os._exit(71)
        jobs.create_backup = interrupted
        store_at(tmp_path).run_next(None)
    process = multiprocessing.get_context('fork').Process(target=crash)
    process.start(); process.join(5)
    assert process.exitcode == 71
    assert store.read(row['id'])['status'] == 'running'
    result = store_at(tmp_path).run_next(None)
    assert result['status'] == 'succeeded'
    assert len(list(store.backups.glob('*.dump'))) == 1
    assert store.run_next(None) is None


def test_two_workers_cannot_execute_the_same_job(store, monkeypatch):
    row = store.enqueue('e' * 32, 'root')
    started, finish = threading.Event(), threading.Event()
    calls = []
    def slow(*args, **kw):
        calls.append(1); started.set(); assert finish.wait(5)
        return good_dump(*args, **kw)
    monkeypatch.setattr(jobs, 'create_backup', slow)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(store.run_next, None)
        assert started.wait(3)
        try: assert pool.submit(store.run_next, None).result(2) is None
        finally: finish.set()
        assert first.result(3)['status'] == 'succeeded'
    assert calls == [1] and store.read(row['id'])['attempts'] == 1


def test_other_backup_operation_leaves_job_queued(store, monkeypatch):
    row = store.enqueue('f' * 32, 'root')
    with backup_files.backup_lock(store.backups):
        assert store.run_next(None)['status'] == 'queued'
    assert store.read(row['id'])['attempts'] == 0
    assert store.run_next(None)['status'] == 'succeeded'


def test_failure_is_visible_and_does_not_publish_result(store, monkeypatch):
    row = store.enqueue('g' * 32, 'root')
    def fail(*args, **kw): raise backup_files.BackupError('PostgreSQL не створив копію')
    monkeypatch.setattr(jobs, 'create_backup', fail)
    assert store.run_next(None)['status'] == 'failed'
    assert store.read(row['id'])['result'] is None
    assert not list(store.backups.glob('*.dump'))
    assert store.enqueue('g' * 32, 'root')['status'] == 'failed'


def test_worker_availability_expires(store):
    assert store.worker_state() == {'available': False}
    store.heartbeat(); assert store.worker_state() == {'available': True}
    os.utime(store.directory / '.heartbeat', (1, 1))
    assert store.worker_state() == {'available': False}


@pytest.mark.parametrize('key', ['short', '../' * 10, 'x' * 81])
def test_invalid_keys_cannot_create_files(store, key):
    with pytest.raises(ValueError): store.enqueue(key, 'root')
    assert store.recent() == []


def test_old_sync_endpoint_fails_closed(store, monkeypatch):
    monkeypatch.setattr(backups, 'configured_store', lambda: store)
    with pytest.raises(HTTPException) as error:
        asyncio.run(backups.create(who=SimpleNamespace(login='root')))
    assert error.value.status_code == 409 and not store.recent()


def test_corrupt_state_is_reported_without_disclosing_file_paths(store, monkeypatch):
    row = store.enqueue('h' * 32, 'root')
    (store.directory / (row['id'] + '.json')).write_text('{broken')
    monkeypatch.setattr(backups, 'configured_store', lambda: store)
    with pytest.raises(HTTPException) as error: asyncio.run(backups.jobs(who=None))
    assert error.value.status_code == 503
    assert str(store.directory) not in error.value.detail


def test_maintenance_entrypoint_starts_without_optional_telegram_and_stops_cleanly(tmp_path):
    import subprocess, sys, time
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'PYTHONPATH':str(root), 'ELFAR_DATA_ROOT':str(tmp_path),
           'PUBLIC_URL':'http://localhost', 'BOT_TOKEN':'', 'OPTIONAL_TELEGRAM':'true'}
    with (tmp_path/'worker-output.log').open('wb') as output:
        process = subprocess.Popen([sys.executable, '-m', 'maintenance'], cwd=root, env=env,
                                   stdout=output, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if (tmp_path/'jobs/.heartbeat').exists(): break
                assert process.poll() is None, (tmp_path/'worker-output.log').read_text()
                time.sleep(.05)
            else: pytest.fail('Maintenance heartbeat startup timeout')
            assert store_at(tmp_path).worker_state()['available']
            process.terminate(); assert process.wait(5) == 0
        finally:
            if process.poll() is None: process.kill(); process.wait(5)
