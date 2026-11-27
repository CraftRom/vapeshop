from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class StaffMixin:
    async def create_operator(self, data: dict) -> Operator:
        row = m.Operator(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _operator(row)

    async def get_operator(self, operator_id) -> Operator | None:
        return _operator(await self.s.get(m.Operator, operator_id))

    async def get_operator_by_login(self, login: str) -> Operator | None:
        row = await self.s.scalar(select(m.Operator).where(m.Operator.login == login))
        return _operator(row)

    async def list_operators(self) -> list[Operator]:
        rows = await self.s.scalars(select(m.Operator).order_by(m.Operator.id))
        return [_operator(r) for r in rows]

    async def update_operator(self, operator_id, data: dict) -> Operator | None:
        row = await self.s.get(m.Operator, operator_id)
        if not row:
            return None
        if "password_hash" in data or (data.get("is_active") is False and row.is_active):
            row.auth_version += 1
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        await self.s.refresh(row)
        return _operator(row)

    async def purge_operator(self, operator_id) -> bool:
        row = await self.s.get(m.Operator, operator_id)
        if not row:
            return False
        # Імʼя в замовленні — знімок, воно лишається; прибираємо тільки звʼязок
        await self.s.execute(
            update(m.Order).where(m.Order.operator_id == operator_id)
            .values(operator_id=None)
        )
        await self.s.delete(row)
        await self._commit()
        return True

    async def delete_operator(self, operator_id) -> bool:
        row = await self.s.get(m.Operator, operator_id)
        if not row:
            return False
        if row.is_active:
            row.auth_version += 1
        row.is_active = False
        await self.s.commit()
        return True
