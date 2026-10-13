"""Disposable per-run SQLite paths, independent of production DATABASE_URL.

The shell runner provides a fresh QA_DATA_DIR. Standalone Python suites get
their own directory, automatically removed at interpreter shutdown.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory

_temporary = None
if not os.environ.get("QA_DATA_DIR"):
    _temporary = TemporaryDirectory(prefix="elfar-qa-")
    os.environ["QA_DATA_DIR"] = _temporary.name
QA_DATA_DIR = Path(os.environ["QA_DATA_DIR"]).resolve()
QA_DATA_DIR.mkdir(parents=True, exist_ok=True)


def qa_db_path(name: str) -> str:
    if Path(name).name != name or not name.endswith(".db"):
        raise ValueError("QA database must be a simple .db filename")
    return str(QA_DATA_DIR / name)


def qa_db_url(name: str) -> str:
    return "sqlite+aiosqlite:///" + qa_db_path(name)
