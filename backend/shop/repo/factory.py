"""Вибір бекенду бази за конфігурацією.

DB_BACKEND=sql       — Postgres/SQLite через SQLAlchemy (власний сервер)
DB_BACKEND=firestore — Firestore (Vercel та інший serverless)
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from shop.config import settings
from shop.repo.base import Repository

log = logging.getLogger("repo")

_firestore_store = None


def _get_firestore_store():
    """Клієнт створюється один раз на процес — у serverless це холодний старт."""
    global _firestore_store
    if _firestore_store is None:
        from shop.repo.firestore_store import FirestoreDocStore

        _firestore_store = FirestoreDocStore(
            project=settings.firebase_project or None,
            database=settings.firebase_database or None,
        )
        log.info("Firestore підключено (проєкт %s)", settings.firebase_project or "за замовчуванням")
    return _firestore_store


@asynccontextmanager
async def open_repo() -> AsyncIterator[Repository]:
    if settings.db_backend == "firestore":
        from shop.repo.firestore import FirestoreRepository

        yield FirestoreRepository(_get_firestore_store())
        return

    from shop.db import SessionMaker
    from shop.repo.sql import SqlRepository

    async with SessionMaker() as session:
        yield SqlRepository(session)


async def get_repo() -> AsyncIterator[Repository]:
    """Залежність для FastAPI."""
    async with open_repo() as repo:
        yield repo
