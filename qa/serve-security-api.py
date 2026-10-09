"""Local QA only: isolated SQLite and fake Telegram; never a deployment entrypoint."""
from qa_common import boot
app, Session, fake = boot('/tmp/security-browser.db')
from shop.config import settings
settings.public_url = ''
settings.cors_origins = 'http://127.0.0.1:5176'
settings.trusted_hosts = 'localhost,127.0.0.1'
# Allowed hosts are captured at import time; qa_common already supplies localhost.
import uvicorn
uvicorn.run(app, host='127.0.0.1', port=8000, lifespan='off', access_log=False, server_header=False)
