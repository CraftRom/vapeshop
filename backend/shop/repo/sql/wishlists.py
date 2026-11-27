from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class WishlistsMixin:
    async def list_wishlists(self, user_id) -> list[Wishlist]:
        rows = await self.s.scalars(
            select(m.Wishlist).where(m.Wishlist.user_id == user_id)
            .order_by(m.Wishlist.id)
        )
        return [_wishlist(r) for r in rows]

    async def get_wishlist(self, wishlist_id) -> Wishlist | None:
        return _wishlist(await self.s.get(m.Wishlist, wishlist_id))

    async def create_wishlist(self, user_id, name: str) -> Wishlist:
        row = m.Wishlist(user_id=user_id, name=name, product_ids=[])
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _wishlist(row)

    async def rename_wishlist(self, wishlist_id, name: str) -> Wishlist | None:
        row = await self.s.get(m.Wishlist, wishlist_id)
        if not row:
            return None
        row.name = name
        await self.s.commit()
        await self.s.refresh(row)
        return _wishlist(row)

    async def delete_wishlist(self, wishlist_id) -> bool:
        row = await self.s.get(m.Wishlist, wishlist_id)
        if not row:
            return False
        await self.s.delete(row)
        await self.s.commit()
        return True

    async def set_wishlist_items(self, wishlist_id, product_ids: list[int]) -> Wishlist | None:
        row = await self.s.get(m.Wishlist, wishlist_id)
        if not row:
            return None
        # Новий список, а не мутація на місці: SQLAlchemy не помічає зміну
        # всередині JSON-колонки й не збереже її
        row.product_ids = list(product_ids)
        await self.s.commit()
        await self.s.refresh(row)
        return _wishlist(row)
