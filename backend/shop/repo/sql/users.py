from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class UsersMixin:
    async def get_user_by_tg(self, tg_id: int) -> User | None:
        return _user(await self.s.scalar(select(m.User).where(m.User.tg_id == tg_id)))

    async def get_user(self, user_id: int) -> User | None:
        return _user(await self.s.get(m.User, user_id))

    async def get_user_by_referral_code(self, code: str) -> User | None:
        return _user(await self.s.scalar(select(m.User).where(m.User.referral_code == code)))

    async def _unique_code(self) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(8))
            if not await self.s.scalar(select(m.User.id).where(m.User.referral_code == code)):
                return code

    async def create_user(self, tg_id, username, first_name, referrer_id) -> User:
        row = m.User(
            tg_id=tg_id, username=username, first_name=first_name,
            referral_code=await self._unique_code(), referrer_id=referrer_id,
            search_key=user_search_key(username, first_name, None),
        )
        self.s.add(row)
        if referrer_id:
            await self.s.execute(
                update(m.User).where(m.User.id == referrer_id)
                .values(referrals_count=m.User.referrals_count + 1)
            )
        await self._commit()
        await self.s.refresh(row)
        return _user(row)

    async def touch_user(self, user, username, first_name) -> User:
        await self.s.execute(
            update(m.User).where(m.User.id == user.id).values(
                username=username or user.username,
                first_name=first_name or user.first_name,
                last_seen_at=datetime.now(timezone.utc),
                search_key=user_search_key(
                    username or user.username, first_name or user.first_name, user.phone
                ),
            )
        )
        await self._commit()
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        return user

    async def set_user_phone(self, user_id: int, phone: str | None) -> User | None:
        row = await self.s.get(m.User, user_id)
        if not row:
            return None
        clean = (phone or "").strip() or None
        row.phone = clean
        row.search_key = user_search_key(row.username, row.first_name, clean)
        await self._commit()
        return _user(await self.s.get(m.User, user_id))

    async def set_user_referrer(self, user, referrer_id: int) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user.id).values(referrer_id=referrer_id)
        )
        await self.s.execute(
            update(m.User).where(m.User.id == referrer_id)
            .values(referrals_count=m.User.referrals_count + 1)
        )
        await self._commit()
        user.referrer_id = referrer_id

    async def confirm_age(self, user) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user.id).values(age_confirmed=True)
        )
        await self._commit()
        user.age_confirmed = True

    async def set_blocked(self, user_id: int, blocked: bool) -> User | None:
        row = await self.s.get(m.User, user_id)
        if not row:
            return None
        row.is_blocked = blocked
        await self.s.commit()
        return _user(row)

    async def add_bonus(self, user_id, amount, reason, order_id=None) -> None:
        self.s.add(m.BonusTx(user_id=user_id, amount=amount, reason=reason, order_id=order_id))
        await self.s.execute(
            update(m.User).where(m.User.id == user_id)
            .values(bonus_balance=m.User.bonus_balance + amount)
        )
        await self._commit()

    async def update_user_totals(self, user_id, orders_delta, spent_delta) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user_id).values(
                orders_count=_not_below_zero(m.User.orders_count + orders_delta),
                total_spent=_not_below_zero(m.User.total_spent + spent_delta),
            )
        )
        await self._commit()

    async def _apply_business_state_row(
        self, row: m.Order, state: str, moment: datetime,
    ) -> bool:
        """Змінює persisted business state і customer totals без COMMIT.

        Допоміжний метод навмисно спільний для CRM patch і прямого переходу:
        статус SalesDrive, ``business_state`` та денормалізовані totals мають
        потрапляти в одну транзакцію, а не лишати коротке вікно розсинхрону.
        """
        from shop.services.order_business import BUSINESS_SALE, BUSINESS_STATES

        normalized = str(state or "").strip().lower()
        if normalized not in BUSINESS_STATES:
            raise ValueError(f"Невідомий business_state: {state}")
        previous = str(row.business_state or "pending").strip().lower()
        if previous == normalized:
            if row.business_state_at is None:
                row.business_state_at = moment
            return False

        user_row = await self.s.scalar(
            select(m.User).where(m.User.id == row.user_id).with_for_update()
        )
        amount = Decimal(str(row.total or 0))
        if user_row and previous == BUSINESS_SALE and normalized != BUSINESS_SALE:
            user_row.orders_count = max(0, int(user_row.orders_count or 0) - 1)
            user_row.total_spent = max(
                Decimal(0), Decimal(str(user_row.total_spent or 0)) - amount,
            )
        elif user_row and previous != BUSINESS_SALE and normalized == BUSINESS_SALE:
            user_row.orders_count = int(user_row.orders_count or 0) + 1
            user_row.total_spent = Decimal(str(user_row.total_spent or 0)) + amount

        row.business_state = normalized
        row.business_state_at = moment
        return True

    async def set_order_business_state(
        self, order_id: int, state: str, *, changed_at: datetime | None = None
    ) -> Order | None:
        """Атомарне джерело істини для sale/refusal і customer totals.

        Лічильники клієнта рухаються лише при вході/виході зі ``sale``.
        Повторний webhook або pull з тим самим станом є ідемпотентним.
        """
        moment = changed_at or datetime.now(timezone.utc)
        try:
            row = await self.s.scalar(
                select(m.Order).where(m.Order.id == order_id).with_for_update()
                .options(selectinload(m.Order.items), selectinload(m.Order.user))
            )
            if not row:
                await self.s.rollback()
                return None
            was_closed = is_closed(row)
            await self._apply_business_state_row(row, state, moment)
            record_completion(row, was_closed, moment)
            await self.s.commit()
            loaded = await self.s.scalar(
                select(m.Order).where(m.Order.id == order_id)
                .options(selectinload(m.Order.items), selectinload(m.Order.user))
            )
            fresh = _order(loaded, with_user=True)
            _emit_order_changed(fresh, ("business_state",))
            return fresh
        except Exception:
            await self.s.rollback()
            raise

    async def list_users(self, search=None, blocked=None, limit=100, offset=0) -> list[User]:
        query = self._user_filters(select(m.User), search, blocked)
        query = query.order_by(m.User.created_at.desc(), m.User.id.desc()).limit(limit).offset(offset)
        return [_user(r) for r in await self.s.scalars(query)]

    @staticmethod
    def _user_filters(query, search=None, blocked=None):
        if search:
            query = query.where(m.User.search_key.contains(search.lower(), autoescape=True))
        if blocked is not None:
            query = query.where(m.User.is_blocked.is_(blocked))
        return query

    async def count_filtered_users(self, search=None, blocked=None):
        query = self._user_filters(select(func.count()).select_from(m.User), search, blocked)
        return int(await self.s.scalar(query) or 0)
