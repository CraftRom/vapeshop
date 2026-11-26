"""Bot log from the VPS: heartbeat failures and Telegram polling transients."""
import asyncio
import json
import logging

import pytest

from bot.polling_log import TransientPollingFilter
from shop import worker_health


def record(message, level=logging.ERROR, name='aiogram.dispatcher'):
    return logging.LogRecord(name, level, __file__, 1, message, None, None)


@pytest.mark.parametrize('message', [
    'Failed to fetch updates - TelegramServerError: Telegram server says - Bad Gateway',
    'Failed to fetch updates - TelegramNetworkError: HTTP Client says - Request timeout error',
    'Failed to fetch updates - TelegramNetworkError: HTTP Client says - ClientOSError: [Errno 104] Connection reset by peer',
    "Failed to fetch updates - TelegramRetryAfter: Telegram server says - Flood control exceeded on method 'GetUpdates'. Retry in 5 seconds",
])
def test_transient_polling_failures_become_warnings(message):
    entry = record(message)
    assert TransientPollingFilter().filter(entry)
    assert entry.levelno == logging.WARNING and entry.levelname == 'WARNING'
    assert entry.event == 'telegram.polling.transient'


@pytest.mark.parametrize('message', [
    'Failed to fetch updates - TelegramUnauthorizedError: Telegram server says - Unauthorized',
    'Failed to fetch updates - TelegramConflictError: Telegram server says - Conflict: terminated by other getUpdates request',
    'Cause exception while process update id=1 by bot id=2',
])
def test_real_errors_stay_errors(message):
    entry = record(message)
    assert TransientPollingFilter().filter(entry)
    assert entry.levelno == logging.ERROR and not hasattr(entry, 'event')


def test_json_log_carries_the_transient_event():
    from shop.logging_setup import JsonFormatter
    entry = record('Failed to fetch updates - TelegramServerError: Telegram server says - Bad Gateway')
    TransientPollingFilter().filter(entry)
    line = json.loads(JsonFormatter('bot').format(entry))
    assert line['level'] == 'warning' and line['event'] == 'telegram.polling.transient'


def test_bot_installs_the_filter_once():
    from bot.polling_log import install
    install(); install()
    filters = [f for f in logging.getLogger('aiogram.dispatcher').filters if isinstance(f, TransientPollingFilter)]
    assert len(filters) == 1


def run_pulse(monkeypatch, directory, outcomes):
    """Drive pulse() with one simulated minute per beat; stops after the outcomes."""
    stop = asyncio.Event()
    queue = list(outcomes)
    def beat(*args, **kwargs):
        if not queue:
            stop.set(); return
        if queue.pop(0) == 'fail':
            if not queue: stop.set()
            raise PermissionError(13, 'Permission denied')
        if not queue: stop.set()
    monkeypatch.setattr(worker_health, 'beat', beat)
    monkeypatch.setitem(worker_health.WORKERS['bot'], 'interval', 0)
    minutes = iter(range(0, 10_000))
    asyncio.run(asyncio.wait_for(
        worker_health.pulse('bot', stop, directory=directory, clock=lambda: next(minutes) * 60.0), 10))


def test_heartbeat_failure_is_explained_once_then_throttled(tmp_path, monkeypatch, caplog):
    locked = tmp_path / 'heartbeats'
    locked.mkdir()
    caplog.set_level(logging.INFO, logger='worker_health')
    run_pulse(monkeypatch, locked, ['fail'] * 25)  # 25 failing beats, a minute apart
    failed = [r for r in caplog.records if getattr(r, 'event', '') == 'worker.heartbeat.failed']
    assert 2 <= len(failed) <= 3, len(failed)  # not 25 identical lines
    first = failed[0]
    assert 'немає права запису' in first.getMessage() and str(locked) in first.getMessage()
    assert first.errno == 13 and first.errorType == 'PermissionError'
    assert failed[1].suppressed >= 8


def test_heartbeat_recovery_is_logged_once(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='worker_health')
    run_pulse(monkeypatch, tmp_path, ['fail', 'fail', 'ok', 'ok', 'ok'])
    events = [getattr(r, 'event', '') for r in caplog.records]
    assert events.count('worker.heartbeat.failed') == 1 and events.count('worker.heartbeat.recovered') == 1
