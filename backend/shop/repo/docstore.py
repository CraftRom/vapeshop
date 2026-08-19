"""Мінімальний інтерфейс документного сховища.

Репозиторій Firestore спілкується з базою лише через цей інтерфейс. Завдяки
цьому вся його логіка — денормалізація, розбиття запитів, курсори — тестується
на пам'яті, без мережі й без облікових записів Google.

Реалізацій дві:
  • InMemoryDocStore — для тестів, повторює обмеження Firestore;
  • FirestoreDocStore — справжній клієнт (shop/repo/firestore_store.py).

Навмисно не додано нічого, чого Firestore не вміє: жодних JOIN, OR між
різними полями, пошуку підрядка. Якщо операція не виражається тут — значить,
її треба вирішувати денормалізацією, а не хитрішим запитом.
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Inc:
    """Атомарний інкремент поля. Firestore робить його на сервері."""
    by: float


Filter = tuple[str, str, Any]        # (поле, оператор, значення)
Order = tuple[str, str]              # (поле, "asc" | "desc")

OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "in", "array_contains"}


class DocStore(ABC):
    @abstractmethod
    async def get(self, collection: str, doc_id: str) -> dict | None: ...

    @abstractmethod
    async def set(self, collection: str, doc_id: str, data: dict) -> None: ...

    @abstractmethod
    async def update(self, collection: str, doc_id: str, data: dict) -> bool:
        """Часткове оновлення. Значення Inc застосовуються атомарно."""

    @abstractmethod
    async def delete(self, collection: str, doc_id: str) -> bool: ...

    @abstractmethod
    async def query(
        self, collection: str, filters: list[Filter] | None = None,
        order_by: list[Order] | None = None, limit: int | None = None, offset: int = 0,
    ) -> list[dict]: ...

    @abstractmethod
    async def count(self, collection: str, filters: list[Filter] | None = None) -> int: ...

    @abstractmethod
    async def next_id(self, name: str) -> int:
        """Наступний номер послідовності. Firestore не має автоінкременту,
        тому тримаємо лічильники в окремій колекції й рухаємо їх транзакційно."""

    async def close(self) -> None:
        return None


# --------------------------------------------------------------- фейк на пам'яті

def _matches(doc: dict, field: str, op: str, value: Any) -> bool:
    actual = doc.get(field)
    if op == "==":
        return actual == value
    if op == "!=":
        return actual != value
    if op == "in":
        return actual in value
    if op == "array_contains":
        return isinstance(actual, list) and value in actual
    if actual is None:
        return False        # Firestore не повертає документи без поля в range-фільтрі
    try:
        if op == "<":
            return actual < value
        if op == "<=":
            return actual <= value
        if op == ">":
            return actual > value
        if op == ">=":
            return actual >= value
    except TypeError:
        return False
    raise ValueError(f"Невідомий оператор: {op}")


class InMemoryDocStore(DocStore):
    """Повторює семантику Firestore рівно настільки, наскільки її використовує код."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict]] = {}
        self.counters: dict[str, int] = {}
        self.query_log: list[tuple[str, tuple]] = []   # для перевірки, що індекси потрібні

    def _col(self, collection: str) -> dict[str, dict]:
        return self.data.setdefault(collection, {})

    async def get(self, collection, doc_id):
        doc = self._col(collection).get(str(doc_id))
        return copy.deepcopy(doc) if doc else None

    async def set(self, collection, doc_id, data):
        self._col(collection)[str(doc_id)] = copy.deepcopy(data)

    async def update(self, collection, doc_id, data):
        doc = self._col(collection).get(str(doc_id))
        if doc is None:
            return False
        for key, value in data.items():
            if isinstance(value, Inc):
                doc[key] = (doc.get(key) or 0) + value.by
            else:
                doc[key] = copy.deepcopy(value)
        return True

    async def delete(self, collection, doc_id):
        return self._col(collection).pop(str(doc_id), None) is not None

    async def query(self, collection, filters=None, order_by=None, limit=None, offset=0):
        filters = filters or []
        for field, op, _ in filters:
            if op not in OPERATORS:
                raise ValueError(f"Оператор {op} не підтримується Firestore")
        self.query_log.append((collection, tuple((f[0], f[1]) for f in filters)))

        rows = [
            copy.deepcopy(doc)
            for doc in self._col(collection).values()
            if all(_matches(doc, f, op, v) for f, op, v in filters)
        ]

        for field, direction in reversed(order_by or []):
            rows.sort(
                key=lambda d: (d.get(field) is None, d.get(field)),
                reverse=(direction == "desc"),
            )

        rows = rows[offset:]
        return rows[:limit] if limit is not None else rows

    async def count(self, collection, filters=None):
        return len(await self.query(collection, filters))

    async def next_id(self, name):
        self.counters[name] = self.counters.get(name, 0) + 1
        return self.counters[name]
