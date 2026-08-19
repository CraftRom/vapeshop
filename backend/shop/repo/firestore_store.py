"""Справжній клієнт Firestore.

Це єдиний шар, який не покривається тестами в цьому середовищі: емулятор
Firestore тягне jar із storage.googleapis.com, недоступного звідси. Логіка
репозиторію тестується через InMemoryDocStore, а тут — лише прямі виклики SDK.
Перед продакшеном прогоніть tests_repo.py проти емулятора (див. docs/FIREBASE.md).
"""
from __future__ import annotations

import logging

from google.api_core import exceptions as gexc
from google.cloud.firestore import AsyncClient, Increment
from google.cloud.firestore_v1.base_query import FieldFilter

from shop.repo.docstore import DocStore, Inc

log = logging.getLogger("firestore")

DIRECTIONS = {"asc": "ASCENDING", "desc": "DESCENDING"}


class FirestoreDocStore(DocStore):
    def __init__(self, project: str | None = None, database: str | None = None) -> None:
        kwargs: dict = {}
        if project:
            kwargs["project"] = project
        if database:
            kwargs["database"] = database
        self.client = AsyncClient(**kwargs)

    def _col(self, collection: str):
        return self.client.collection(collection)

    async def get(self, collection, doc_id):
        snapshot = await self._col(collection).document(str(doc_id)).get()
        return snapshot.to_dict() if snapshot.exists else None

    async def set(self, collection, doc_id, data):
        await self._col(collection).document(str(doc_id)).set(data)

    async def update(self, collection, doc_id, data):
        payload = {
            key: (Increment(value.by) if isinstance(value, Inc) else value)
            for key, value in data.items()
        }
        try:
            await self._col(collection).document(str(doc_id)).update(payload)
            return True
        except gexc.NotFound:
            return False

    async def delete(self, collection, doc_id):
        doc = self._col(collection).document(str(doc_id))
        snapshot = await doc.get()
        if not snapshot.exists:
            return False
        await doc.delete()
        return True

    def _build(self, collection, filters, order_by, limit, offset):
        query = self._col(collection)
        for field, op, value in filters or []:
            query = query.where(filter=FieldFilter(field, op, value))
        for field, direction in order_by or []:
            query = query.order_by(field, direction=DIRECTIONS[direction])
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query

    async def query(self, collection, filters=None, order_by=None, limit=None, offset=0):
        query = self._build(collection, filters, order_by, limit, offset)
        try:
            return [doc.to_dict() async for doc in query.stream()]
        except gexc.FailedPrecondition as exc:
            # Firestore вимагає складений індекс під кожну комбінацію фільтрів.
            # Повідомлення від Google містить готове посилання на створення.
            log.error("Потрібен складений індекс для %s: %s", collection, exc)
            raise

    async def count(self, collection, filters=None):
        query = self._build(collection, filters, None, None, 0)
        result = await query.count().get()
        return int(result[0][0].value) if result else 0

    async def next_id(self, name):
        """Лічильник у транзакції — Firestore не має автоінкременту.

        Обмеження платформи: один документ витримує ~1 запис/с. Для магазину
        цього вистачає з запасом; при потребі можна перейти на розподілений
        лічильник із шардами.
        """
        doc = self._col("_counters").document(name)

        @self.client.transactional
        async def bump(transaction):
            snapshot = await doc.get(transaction=transaction)
            current = snapshot.to_dict().get("value", 0) if snapshot.exists else 0
            new_value = current + 1
            transaction.set(doc, {"value": new_value})
            return new_value

        return await bump(self.client.transaction())

    async def close(self):
        self.client.close()
