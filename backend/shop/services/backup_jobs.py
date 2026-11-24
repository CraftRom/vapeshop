"""Durable local-volume jobs. flock fences processes; output names fence crash retries."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import time

from shop.backup_files import (BackupBusy, BackupError, backup_lock, staging_file,
                              create_backup, validate_dump)

ID = re.compile(r'^[a-f0-9]{32}$')
PENDING = {'queued', 'running'}


def atomic_json(path, payload):
    with staging_file(path.parent) as temporary:
        with temporary.open('w') as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


class JobStore:
    def __init__(self, directory, backups):
        self.directory = Path(directory)
        self.backups = Path(backups)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def read(self, job_id):
        if not isinstance(job_id, str) or not ID.fullmatch(job_id):
            raise FileNotFoundError('Завдання не знайдено')
        path = self.directory / (job_id + '.json')
        if path.is_symlink(): raise BackupError('Некоректний журнал завдання')
        try: data = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeError):
            raise BackupError('Пошкоджений журнал завдання; потрібна перевірка диска') from None
        if (not isinstance(data, dict) or data.get('id') != job_id
            or not isinstance(data.get('status'), str) or data['status'] not in PENDING | {'succeeded', 'failed'}
            or data.get('output') != 'elfar-job-' + job_id + '.dump'
            or not all(isinstance(data.get(field), (int, float)) for field in ('created_at', 'updated_at'))
            or not isinstance(data.get('attempts'), int) or data['attempts'] < 0):
            raise BackupError('Некоректний журнал завдання')
        return data

    def recent(self, limit=20):
        rows = [self.read(p.stem) for p in self.directory.glob('*.json') if ID.fullmatch(p.stem)]
        return sorted(rows, key=lambda r: r['created_at'], reverse=True)[:limit]

    def enqueue(self, key, actor):
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
            raise ValueError('Некоректний ключ запиту')
        job_id = hashlib.sha256(('backup:' + key).encode()).hexdigest()[:32]
        with backup_lock(self.directory):
            request_path = self.directory / ('request-' + job_id + '.json')
            if request_path.exists():
                if request_path.is_symlink(): raise BackupError('Некоректний журнал запиту')
                try: target_id = json.loads(request_path.read_text())['id']
                except (ValueError, KeyError, TypeError): raise BackupError('Некоректний журнал запиту') from None
                return self.read(target_id)
            try: return self.read(job_id)
            except FileNotFoundError: pass
            active = next((r for r in self.recent(limit=100000) if r['status'] in PENDING), None)
            if active:
                atomic_json(request_path, {'id': active['id']})
                return active
            row = {'id': job_id, 'kind': 'database_backup', 'status': 'queued',
                   'created_at': time.time(), 'updated_at': time.time(), 'attempts': 0,
                   'requested_by': actor, 'output': 'elfar-job-' + job_id + '.dump',
                   'message': 'Очікує виконавця', 'result': None}
            atomic_json(self.directory / (job_id + '.json'), row)
            return row

    def worker_state(self):
        try: age = time.time() - (self.directory / '.heartbeat').stat().st_mtime
        except OSError: return {'available': False}
        return {'available': 0 <= age < 45}

    def heartbeat(self):
        path = self.directory / '.heartbeat'
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd); path.touch()

    def run_next(self, settings):
        for candidate in reversed(self.recent(limit=100000)):
            if candidate['status'] not in PENDING: continue
            job_id = candidate['id']
            # Separate per-job lock; the process holds it throughout pg_dump.
            lock_dir = self.directory / ('.lock-' + job_id)
            try:
                with backup_lock(lock_dir):
                    row = self.read(job_id)
                    if row['status'] not in PENDING: continue
                    output = self.backups / row['output']
                    path = self.directory / (job_id + '.json')
                    try:
                        # Handles a crash after atomic output publication but before ack.
                        if output.exists():
                            validate_dump(output)
                            ready = output
                        else:
                            if row['attempts'] >= 3:
                                raise BackupError('Перевищено кількість відновлень завдання. Створіть новий запит.')
                            row.update(status='running', attempts=row['attempts'] + 1,
                                       updated_at=time.time(), message='Створюємо та перевіряємо копію')
                            atomic_json(path, row)
                            ready = create_backup(self.backups, settings, output_name=row['output'])
                        row.update(status='succeeded', message='Копія готова', updated_at=time.time(),
                                   result={'name': ready.name, 'sizeBytes': ready.stat().st_size})
                    except BackupBusy:
                        row.update(status='queued', attempts=max(0, row['attempts'] - 1),
                                   message='Очікує завершення іншої операції з копіями', updated_at=time.time())
                    except (BackupError, OSError) as exc:
                        row.update(status='failed', message=str(exc) if isinstance(exc, BackupError)
                                   else 'Не вдалося зберегти копію. Перевірте диск і права доступу.', updated_at=time.time())
                    atomic_json(path, row)
                    return row
            except BackupBusy:
                continue
        return None


def configured_store():
    from shop.paths import DATA_ROOT, backups_dir
    return JobStore(DATA_ROOT / 'jobs', backups_dir())
