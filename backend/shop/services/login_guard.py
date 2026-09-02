"""Стримування підбору пароля до панелі.

Обмеження в nginx рахує спроби за адресою: п'ять на хвилину з однієї.
Проти підбору з десяти адрес одночасно воно безсиле — рівно як обмеження
швидкості виявилося безсилим проти повільного сканування, яке йшло два
запити на секунду при межі тридцять. Обидва випадки — та сама помилка:
міряти темп там, де ознакою є намір.

Тут рахуємо інакше: невдалі спроби **на обліковий запис**, звідки б вони
не приходили. Логін у панелі один на людину, і десять поспіль невірних
паролів до нього — це не друкарська помилка.

Лічильник живе в пам'яті процесу. Для нашого розгортання це точно: API
працює одним робочим процесом (`--workers 1` у docker-compose.prod.yml).
Якби процесів стало більше, поріг помножився б на їх кількість — тому
поруч стоїть перевірка в наборі, яка про це нагадає, а не мовчазна
поломка через півроку.

Чому в пам'яті, а не в базі. Лічильник скидається при перезапуску — і це
прийнятно: перезапуск відбувається під час деплою, а не за бажанням
зловмисника, і зайвих десять спроб раз на кілька днів нічого не міняють.
Натомість запис у базу на кожну невдалу спробу — це готовий спосіб
покласти базу самим підбором.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


def max_attempts() -> int:
    """Скільки невдалих спроб поспіль дозволено."""
    try:
        value = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "10"))
    except ValueError:
        value = 10
    # Менше трьох — і людина блокує себе сама, переплутавши розкладку.
    return max(3, value)


def lock_seconds() -> int:
    """На скільки закривається вхід після перевищення."""
    try:
        value = int(os.environ.get("LOGIN_LOCK_MINUTES", "15"))
    except ValueError:
        value = 15
    # Чверть години зупиняє перебір і не перетворює друкарську помилку на
    # втрачений робочий день: за цей час встигають знайти правильний
    # пароль, а перебирати мільйони варіантів по десять на чверть години
    # не має сенсу.
    return max(1, value) * 60


@dataclass
class _State:
    failures: int = 0
    locked_until: float = 0.0
    last_failure: float = field(default_factory=time.monotonic)


_states: dict[str, _State] = {}


def _key(login: str) -> str:
    return login.strip().lower()


def _prune(now: float) -> None:
    """Прибирає давні записи, щоб словник не ріс за тижні роботи."""
    if len(_states) < 500:
        return
    cutoff = now - lock_seconds() * 4
    for key in [k for k, v in _states.items()
                if v.locked_until < now and v.last_failure < cutoff]:
        _states.pop(key, None)


def locked_for(login: str) -> int:
    """Скільки секунд лишилось до розблокування. 0 — вхід відкритий."""
    state = _states.get(_key(login))
    if not state:
        return 0
    left = state.locked_until - time.monotonic()
    return int(left) + 1 if left > 0 else 0


def note_failure(login: str) -> int:
    """Записує невдалу спробу. Повертає кількість поспіль."""
    now = time.monotonic()
    _prune(now)
    state = _states.setdefault(_key(login), _State())

    # Лічильник рахує спроби **поспіль**, а не за весь час: якщо між
    # помилками минуло більше, ніж триває блокування, це вже інша історія,
    # а не продовження попередньої. Інакше людина, яка помиляється раз на
    # місяць, за рік накопичила б блокування на порожньому місці.
    if now - state.last_failure > lock_seconds():
        state.failures = 0

    state.failures += 1
    state.last_failure = now
    if state.failures >= max_attempts():
        state.locked_until = now + lock_seconds()
    return state.failures


def note_success(login: str) -> None:
    """Успішний вхід обнуляє лічильник."""
    _states.pop(_key(login), None)


def reset() -> None:
    """Тільки для наборів перевірок."""
    _states.clear()
