from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class OrderChatMixin:
    async def set_chat_order(self, user_id, order_id) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user_id).values(chat_order_id=order_id)
        )
        await self._commit()

    async def save_order_receipt(self, order_id, user_id, attachment, *, tg_message_id, author, text):
        from shop.services.chat_access import can_chat
        row = await self.s.scalar(
            select(m.Order).where(m.Order.id == order_id, m.Order.user_id == user_id).with_for_update()
        )
        if not row or row.payment_method != "card" or row.total <= 0 or not can_chat(row):
            return None
        if not attachment or attachment.get("file_kind") not in {"photo", "document"}:
            return None
        # FSM isolation serializes this client's updates; the row lock also
        # prevents concurrent receipt writes in separate PostgreSQL sessions.
        existing = await self.s.scalar(select(m.OrderMessage).where(
            m.OrderMessage.order_id == order_id, m.OrderMessage.direction == "in",
            m.OrderMessage.tg_message_id == tg_message_id,
        ))
        if existing:
            return _order_message(existing)
        row.receipt_file_id = attachment["file_id"]
        message = m.OrderMessage(order_id=order_id, user_id=user_id, direction="in",
                                 author=author, text=text, tg_message_id=tg_message_id,
                                 is_read=False, **attachment)
        self.s.add(message)
        try:
            await self.s.commit()
            await self.s.refresh(message)
        except Exception:
            await self.s.rollback()
            raise
        return _order_message(message)

    async def add_order_message(self, data: dict) -> OrderMessage:
        row = m.OrderMessage(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _order_message(row)

    async def list_order_messages(
        self, order_id, limit: int = 200, after_id: int | None = None,
        before_id: int | None = None,
    ) -> list[OrderMessage]:
        """Hot + compressed cold history as one chronological stream.

        Callers do not need to know whether an old dialogue has already been
        archived. IDs are preserved inside the archive, so ``after_id`` and
        ``before_id`` keep exactly the same semantics across the hot/cold
        boundary.
        """
        cap = max(1, min(int(limit or 200), 500))
        if after_id is not None and before_id is not None:
            raise ValueError("after_id і before_id не можна використовувати одночасно")

        archive = await self._message_archive("order", int(order_id))
        archived = [_archived_order_message(x) for x in _unpack_archive(archive)]
        archived = [x for x in archived if x.id > 0]

        query = select(m.OrderMessage).where(m.OrderMessage.order_id == order_id)
        if after_id is not None:
            query = query.where(m.OrderMessage.id > int(after_id)).order_by(m.OrderMessage.id).limit(cap)
            live = [_order_message(r) for r in await self.s.scalars(query)]
            cold = [x for x in archived if x.id > int(after_id)]
            merged = {x.id: x for x in [*cold, *live]}
            return [merged[k] for k in sorted(merged)[:cap]]

        if before_id is not None:
            query = query.where(m.OrderMessage.id < int(before_id)).order_by(m.OrderMessage.id.desc()).limit(cap)
            live_rows = list(await self.s.scalars(query))
            live_rows.reverse()
            live = [_order_message(r) for r in live_rows]
            cold = [x for x in archived if x.id < int(before_id)]
            merged = {x.id: x for x in [*cold, *live]}
            keys = sorted(merged)[-cap:]
            return [merged[k] for k in keys]

        rows = list(await self.s.scalars(
            query.order_by(m.OrderMessage.id.desc()).limit(cap)
        ))
        rows.reverse()
        live = [_order_message(r) for r in rows]
        merged = {x.id: x for x in [*archived, *live]}
        keys = sorted(merged)[-cap:]
        return [merged[k] for k in keys]

    async def find_order_by_tg_message(self, tg_message_id: int, user_id: int | None = None) -> int | None:
        live = select(m.OrderMessage.order_id).where(m.OrderMessage.tg_message_id == tg_message_id)
        if user_id is not None:
            live = live.where(m.OrderMessage.user_id == int(user_id))
        order_id = await self.s.scalar(live.limit(1))
        if order_id is not None:
            return int(order_id)
        archived = select(m.ArchivedMessageRef.entity_id).where(
            m.ArchivedMessageRef.kind == "order",
            m.ArchivedMessageRef.tg_message_id == int(tg_message_id),
        )
        if user_id is not None:
            archived = archived.where(m.ArchivedMessageRef.user_id == int(user_id))
        value = await self.s.scalar(archived.limit(1))
        return int(value) if value is not None else None

    async def _mark_order_message_ids_read(self, order_id, message_ids, direction):
        ids = {int(x) for x in (message_ids or []) if int(x) > 0}
        if not ids:
            return 0
        # Serialize with archival so the ACK cannot be lost at the hot/cold boundary.
        await self.s.scalar(select(m.Order.id).where(m.Order.id == order_id).with_for_update())
        result = await self.s.execute(update(m.OrderMessage).where(
            m.OrderMessage.order_id == order_id, m.OrderMessage.id.in_(ids),
            m.OrderMessage.direction == direction, m.OrderMessage.is_read.is_(False),
        ).values(is_read=True))
        changed = int(result.rowcount or 0)
        archive = await self._message_archive("order", int(order_id))
        items = _unpack_archive(archive)
        cold_changed = 0
        for item in items:
            if int(item.get("id") or 0) in ids and item.get("direction") == direction and not item.get("is_read"):
                item["is_read"] = True
                cold_changed += 1
        if cold_changed:
            archive.payload = _pack_archive(items)
            archive.raw_bytes = len(_archive_json(items))
        await self._commit()
        return changed + cold_changed

    async def mark_messages_read(self, order_id, message_ids=None) -> int:
        return await self._mark_order_message_ids_read(order_id, message_ids, "in")

    async def mark_client_read(self, order_id, message_ids=None) -> int:
        return await self._mark_order_message_ids_read(order_id, message_ids, "out")

    async def forget_chat_files(self, older_than_days: int) -> int:
        """Забуває коди вкладень виконаних замовлень.

        Часом виконання вважаємо updated_at: окремої позначки «коли
        завершили» в замовленні немає, а updated_at міняється при кожній
        зміні статусу, тож для замовлення, яке вже в «Виконано», це і є
        момент останньої дії з ним. Якщо менеджер потім щось поправить,
        відлік почнеться заново — це радше добре: значить, до замовлення
        ще поверталися.

        Назву файлу лишаємо: у стрічці має бути видно, що вкладення було,
        інакше розмова читається як обірвана.
        """
        edge = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        stale = (
            select(m.Order.id)
            .where(m.Order.status == OrderStatus.DONE, m.Order.updated_at < edge)
        )
        result = await self.s.execute(
            update(m.OrderMessage)
            .where(
                m.OrderMessage.order_id.in_(stale),
                m.OrderMessage.file_id.is_not(None),
            )
            .values(file_id=None)
        )

        # Загальна підтримка тепер теж приймає фото й документи. Не можна
        # було додати новий канал вкладень і залишити його поза тією самою
        # політикою зберігання: file_id фактично є ключем доступу до файлу.
        stale_support = (
            select(m.SupportThread.id)
            .where(
                m.SupportThread.status == "closed",
                m.SupportThread.updated_at < edge,
            )
        )
        support_result = await self.s.execute(
            update(m.SupportMessage)
            .where(
                m.SupportMessage.thread_id.in_(stale_support),
                m.SupportMessage.file_id.is_not(None),
            )
            .values(file_id=None)
        )
        await self._commit()
        return int(result.rowcount or 0) + int(support_result.rowcount or 0)

    async def set_bot_reachable(self, tg_id: int, reachable: bool) -> None:
        """Позначає, чи доходять до людини повідомлення бота.

        Пишемо лише при зміні: інакше кожне вдале сповіщення оновлювало б
        рядок користувача й тягло за собою запис у базу на порожньому
        місці.
        """
        await self.s.execute(
            update(m.User)
            .where(m.User.tg_id == tg_id, m.User.bot_reachable.is_(not reachable))
            .values(bot_reachable=reachable)
        )
        await self._commit()

    async def unread_counts(self) -> dict[int, int]:
        rows = await self.s.execute(
            select(m.OrderMessage.order_id, func.count(m.OrderMessage.id))
            .where(m.OrderMessage.direction == "in", m.OrderMessage.is_read.is_(False))
            .group_by(m.OrderMessage.order_id)
        )
        return {order_id: count for order_id, count in rows}
