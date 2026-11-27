from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class PromosMixin:
    async def get_promo_by_code(self, code: str) -> Promo | None:
        return _promo(await self.s.scalar(
            select(m.PromoCode).where(func.upper(m.PromoCode.code) == code.strip().upper())
        ))

    async def get_promo(self, promo_id) -> Promo | None:
        return _promo(await self.s.get(m.PromoCode, promo_id))

    async def list_promos(self) -> list[Promo]:
        return [_promo(r) for r in await self.s.scalars(
            select(m.PromoCode).order_by(m.PromoCode.created_at.desc())
        )]

    async def create_promo(self, data: dict) -> Promo:
        data = {**data, "code": data["code"].strip().upper()}
        row = m.PromoCode(**data)
        self.s.add(row)
        try:
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            if await self.get_promo_by_code(data["code"]):
                raise PromoCodeConflict(data["code"]) from None
            raise
        await self.s.refresh(row)
        return _promo(row)

    async def update_promo(self, promo_id, data: dict) -> Promo | None:
        row = await self.s.get(m.PromoCode, promo_id)
        if not row:
            return None
        if "code" in data:
            data = {**data, "code": data["code"].strip().upper()}
        for key, value in data.items():
            setattr(row, key, value)
        try:
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            existing = await self.get_promo_by_code(data.get("code", ""))
            if existing and existing.id != promo_id:
                raise PromoCodeConflict(existing.code) from None
            raise
        return _promo(row)

    async def promo_uses_by_user(self, promo_id, user_id) -> int:
        return await self.s.scalar(
            select(func.count(m.PromoUsage.id)).where(
                m.PromoUsage.promo_id == promo_id, m.PromoUsage.user_id == user_id
            )
        ) or 0

    async def register_promo_use(self, promo_id, user_id, order_id) -> None:
        self.s.add(m.PromoUsage(promo_id=promo_id, user_id=user_id, order_id=order_id))
        await self.s.execute(
            update(m.PromoCode).where(m.PromoCode.id == promo_id)
            .values(used_count=m.PromoCode.used_count + 1)
        )
        await self._commit()
