"""Private, serialized, atomic PostgreSQL backup files; no application imports."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile

SIGNATURE = b'PGDMP'
# Bearer-session tables. A copy must never carry them: replaying a dump would
# otherwise resurrect sessions revoked after the dump (logout, role change,
# operator removal). Restore additionally empties them in the same transaction.
SESSION_TABLES = ('dashboard_sessions',)
DUMP_ARGS = tuple(f'--exclude-table-data={table}' for table in SESSION_TABLES)


class BackupError(RuntimeError):
    pass


class BackupBusy(BackupError):
    pass


@contextmanager
def backup_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / '.backup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupBusy('Інша операція з копіями вже виконується. Повторіть пізніше.') from None
        yield
    finally:
        os.close(fd)


@contextmanager
def staging_file(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.backup-', suffix='.partial', dir=directory)
    os.close(fd)
    path = Path(name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def unique_name(prefix: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', prefix):
        raise ValueError('Некоректний префікс копії')
    return f'{prefix}-{datetime.now(timezone.utc):%Y-%m-%d_%H%M%S-%f}-{secrets.token_hex(6)}.dump'


def publish(path: Path, target: Path) -> Path:
    """Install a complete file without replacing even an existing symlink/file."""
    with path.open('rb') as handle:
        os.fsync(handle.fileno())
    os.link(path, target)
    path.unlink()
    fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def validate_dump(path: Path, *, command=None) -> None:
    if path.is_symlink() or not path.is_file():
        raise BackupError('Копія відсутня або є символічним посиланням')
    with path.open('rb') as handle:
        if handle.read(len(SIGNATURE)) != SIGNATURE:
            raise BackupError('Потрібна копія PostgreSQL у форматі pg_dump -Fc')
    try:
        result = subprocess.run(command or ['pg_restore', '--list', str(path)],
                                capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError('Не вдалося перевірити структуру копії PostgreSQL') from None
    if result.returncode != 0:
        raise BackupError('Копія PostgreSQL пошкоджена або несумісна')


def pg_args(settings, tool='pg_dump'):
    return [tool, '-h', settings.postgres_host, '-p', str(settings.postgres_port),
            '-U', settings.postgres_user, '-d', settings.postgres_db]


def create_backup(directory: Path, settings, *, daily: str | None = None, output_name: str | None = None) -> Path:
    """Only a checked completed file is visible as .dump. One writer per volume."""
    if daily is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', daily):
        raise ValueError('Некоректна дата копії')
    if output_name is not None and not re.fullmatch(r'elfar-job-[a-f0-9]{32}\.dump', output_name):
        raise ValueError('Некоректне ім’я результату завдання')
    with backup_lock(directory):
        if output_name and (directory / output_name).exists():
            validate_dump(directory / output_name)
            return directory / output_name
        if daily:
            candidates = [*directory.glob(f'elfar-auto-{daily}-*.dump'), directory / f'elfar-{daily}.dump']
            for candidate in candidates:
                if not candidate.exists() or candidate.is_symlink():
                    continue
                try:
                    validate_dump(candidate)
                except BackupError:
                    # Keep evidence, but never let an incomplete legacy file count as ready.
                    os.chmod(candidate, 0o600)
                    candidate.rename(directory / (candidate.name + '.invalid-' + secrets.token_hex(6)))
                else:
                    os.chmod(candidate, 0o600)
                    return candidate
        with staging_file(directory) as temporary:
            try:
                result = subprocess.run(pg_args(settings) + ['-Fc', *DUMP_ARGS, '-f', str(temporary)],
                    env={**os.environ, 'PGPASSWORD': settings.postgres_password},
                    capture_output=True, timeout=1800, check=False)
            except (OSError, subprocess.TimeoutExpired):
                raise BackupError('Створення копії не завершилося. Незавершений файл не опубліковано.') from None
            if result.returncode != 0:
                raise BackupError('PostgreSQL не створив копію. Перевірте підключення та вільне місце.')
            validate_dump(temporary)
            return publish(temporary, directory / (output_name or unique_name('elfar-auto-' + daily if daily else 'elfar-manual')))
