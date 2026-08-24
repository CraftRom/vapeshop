"""Списки бажаного.

Правила зібрані тут, а не в роутері: списками користується вітрина, а
згодом ними ж захоче користуватись бот, і дублювати перевірки не хочеться.
"""
from __future__ import annotations

from shop.entities import DEFAULT_WISHLIST_NAME, Product, Wishlist
from shop.repo.base import Repository

# Обмеження проти випадкового й навмисного розростання. Списків більше
# десятка людина все одно не переглядає, а без стелі один запис міг би
# рости нескінченно — це чужий рахунок за сховище.
MAX_LISTS = 10
MAX_ITEMS = 200


class WishlistError(Exception):
    """Порушення правила, яке треба показати покупцеві."""


async def ensure_lists(repo: Repository, user_id: int) -> list[Wishlist]:
    """Списки покупця. Перший — «Обране» — створюється сам.

    Без цього перше натискання сердечка вимагало б спершу вигадати назву
    списку, і більшість покупців на цьому кроці просто пішла б.
    """
    lists = await repo.list_wishlists(user_id)
    if lists:
        return lists
    return [await repo.create_wishlist(user_id, DEFAULT_WISHLIST_NAME)]


async def create(repo: Repository, user_id: int, name: str) -> Wishlist:
    name = (name or "").strip()
    if not name:
        raise WishlistError("Назва списку не може бути порожньою")

    lists = await repo.list_wishlists(user_id)
    if len(lists) >= MAX_LISTS:
        raise WishlistError(f"Більше {MAX_LISTS} списків не можна")
    if any(existing.name.lower() == name.lower() for existing in lists):
        raise WishlistError("Список із такою назвою вже є")

    return await repo.create_wishlist(user_id, name)


async def owned(repo: Repository, wishlist_id: int, user_id: int) -> Wishlist:
    """Список покупця. Чужий не віддаємо навіть на читання."""
    found = await repo.get_wishlist(wishlist_id)
    if not found or found.user_id != user_id:
        raise WishlistError("Список не знайдено")
    return found


async def toggle(
    repo: Repository, wishlist_id: int, user_id: int, product_id: int
) -> tuple[Wishlist, bool]:
    """Додає товар або прибирає, якщо він уже там. Повертає (список, чи додано)."""
    target = await owned(repo, wishlist_id, user_id)

    if product_id in target.product_ids:
        items = [i for i in target.product_ids if i != product_id]
        added = False
    else:
        product = await repo.get_product(product_id)
        if not product or not product.is_active:
            raise WishlistError("Товар недоступний")
        if len(target.product_ids) >= MAX_ITEMS:
            raise WishlistError(f"У списку вже {MAX_ITEMS} товарів")
        # Нові — на початок: щойно додане цікавить найбільше
        items = [product_id, *target.product_ids]
        added = True

    updated = await repo.set_wishlist_items(wishlist_id, items)
    return updated, added


async def remove(repo: Repository, wishlist_id: int, user_id: int, product_id: int) -> Wishlist:
    target = await owned(repo, wishlist_id, user_id)
    items = [i for i in target.product_ids if i != product_id]
    return await repo.set_wishlist_items(wishlist_id, items)


async def drop(repo: Repository, wishlist_id: int, user_id: int) -> None:
    target = await owned(repo, wishlist_id, user_id)
    lists = await repo.list_wishlists(user_id)
    if len(lists) <= 1:
        # Останній список не видаляємо, а чистимо: інакше сердечко в
        # каталозі не мало б куди додавати, і довелося б створювати список
        # прямо посеред покупки
        await repo.set_wishlist_items(target.id, [])
        return
    await repo.delete_wishlist(target.id)


async def hydrate(repo: Repository, lists: list[Wishlist]) -> list[Wishlist]:
    """Підставляє самі товари. Одне пакетне читання на всі списки разом."""
    wanted = {pid for wl in lists for pid in wl.product_ids}
    if not wanted:
        return lists

    products: dict[int, Product] = {}
    for product in await repo.list_products():
        if product.id in wanted:
            products[product.id] = product

    for wl in lists:
        # Видалені назавжди товари просто зникають зі списку показу;
        # чистити сам список не поспішаємо — товар могли лише приховати
        wl.products = [products[i] for i in wl.product_ids if i in products]
    return lists
