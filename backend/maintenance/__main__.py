import asyncio
import logging
import signal
from contextlib import suppress
from shop.config import settings
from shop.logging_setup import setup
from shop.services.backup_jobs import configured_store


async def main():
    setup('maintenance')
    settings.validate_production_security()
    store = configured_store()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError): loop.add_signal_handler(sig, stop.set)
    async def pulse():
        from shop.worker_health import beat
        while not stop.is_set():
            await asyncio.to_thread(store.heartbeat)
            # Shared module-readiness heartbeat (A04); the job-store one stays for its UI.
            with suppress(Exception): await asyncio.to_thread(beat, 'maintenance')
            with suppress(asyncio.TimeoutError): await asyncio.wait_for(stop.wait(), 5)
    heartbeat = asyncio.create_task(pulse())
    try:
        while not stop.is_set():
            try:
                result = await asyncio.to_thread(store.run_next, settings)
                if result and result['status'] in {'succeeded', 'failed'}:
                    logging.getLogger('maintenance.jobs').log(
                        logging.INFO if result['status'] == 'succeeded' else logging.ERROR,
                        result['message'], extra={'event': 'backup.job.' + result['status'], 'jobId': result['id']})
            except Exception: logging.exception('Не вдалося обробити журнал резервних копій')
            # A02: catalog imports interrupted by an API restart (expired lease)
            # or left queued continue here from their last checkpoint.
            try:
                from shop.services.catalog_import import run_pending
                await run_pending()
            except Exception: logging.exception('Не вдалося продовжити імпорт каталогу')
            with suppress(asyncio.TimeoutError): await asyncio.wait_for(stop.wait(), 2)
    finally:
        stop.set(); await heartbeat


if __name__ == '__main__':
    asyncio.run(main())
