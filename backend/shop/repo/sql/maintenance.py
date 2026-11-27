from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class MaintenanceMixin:
    async def _delete_panel_notifications_for_entity(
        self, kinds: tuple[str, ...] | list[str], entity_id: int
    ) -> int:
        """Прибирає оперативні сповіщення разом із видаленим джерелом.

        PanelNotification — не аудит. Якщо товар/замовлення/support-сесію
        стерли, посилання на неіснуючу сутність не повинно висіти в дзвіночку.
        Read-мітки чистимо явно: у Postgres FK має CASCADE, але SQLite у
        частині локальних запусків працює без foreign_keys=ON.
        """
        ids = list(await self.s.scalars(
            select(m.PanelNotification.id).where(
                m.PanelNotification.kind.in_(tuple(kinds)),
                m.PanelNotification.entity_id == int(entity_id),
            )
        ))
        if not ids:
            return 0
        await self.s.execute(
            delete(m.PanelNotificationRead).where(
                m.PanelNotificationRead.notification_id.in_(ids)
            )
        )
        result = await self.s.execute(
            delete(m.PanelNotification).where(m.PanelNotification.id.in_(ids))
        )
        return int(result.rowcount or 0)

    async def _prune_orphan_panel_notifications(self) -> int:
        """Одноразово/ледаче чистить події, джерело яких уже було видалене.

        Це також лікує записи, створені старими версіями до появи cleanup
        у delete/purge-операціях. Викликається лише на повному refresh центру,
        а не на кожному 10-секундному incremental poll.
        """
        removed = 0
        specs = (
            (("order.created", "order.message"), m.Order),
            (("support.message",), m.SupportThread),
            (("product.created",), m.Product),
        )
        for kinds, model in specs:
            ids = list(await self.s.scalars(
                select(m.PanelNotification.id).where(
                    m.PanelNotification.kind.in_(kinds),
                    m.PanelNotification.entity_id.is_not(None),
                    ~m.PanelNotification.entity_id.in_(select(model.id)),
                )
            ))
            if not ids:
                continue
            await self.s.execute(
                delete(m.PanelNotificationRead).where(
                    m.PanelNotificationRead.notification_id.in_(ids)
                )
            )
            result = await self.s.execute(
                delete(m.PanelNotification).where(m.PanelNotification.id.in_(ids))
            )
            removed += int(result.rowcount or 0)
        if removed:
            await self.s.commit()
        return removed

    async def purge_product(self, product_id) -> bool:
        row = await self.s.get(m.Product, product_id)
        if not row:
            return False
        # Знеособлюємо історію явно: покладатись на ON DELETE SET NULL не можна,
        # бо SQLite за замовчуванням не вмикає перевірку зовнішніх ключів.
        await self.s.execute(
            update(m.OrderItem)
            .where(m.OrderItem.product_id == product_id)
            .values(product_id=None)
        )
        await self.s.execute(delete(m.CartItem).where(m.CartItem.product_id == product_id))
        await self._delete_panel_notifications_for_entity(("product.created",), product_id)
        # products_count у SQL — обчислюване поле (COUNT), окремо його не рухаємо
        await self.s.delete(row)
        await self._commit()
        return True

    async def purge_category(self, category_id) -> int:
        if not await self.s.get(m.Category, category_id):
            return 0
        ids = list(
            await self.s.scalars(
                select(m.Product.id).where(self._category_scope(category_id))
            )
        )
        for product_id in ids:
            await self.purge_product(product_id)
        await self.s.execute(update(m.Subcategory).where(m.Subcategory.category_id == category_id).values(category_id=None))
        row = await self.s.get(m.Category, category_id)
        if row:
            await self.s.delete(row)
            await self.s.commit()
        return len(ids)

    async def purge_promo(self, promo_id) -> bool:
        row = await self.s.get(m.PromoCode, promo_id)
        if not row:
            return False
        # orders.promo_code_id — звичайний FK без ondelete, тож чистимо вручну,
        # інакше Postgres відмовить у видаленні.
        await self.s.execute(
            update(m.Order).where(m.Order.promo_code_id == promo_id).values(promo_code_id=None)
        )
        await self.s.execute(delete(m.PromoUsage).where(m.PromoUsage.promo_id == promo_id))
        await self.s.delete(row)
        await self._commit()
        return True

    # --------------------------------------------- cold-tier повідомлень

    async def _message_archive(self, kind: str, entity_id: int):
        return await self.s.scalar(
            select(m.MessageArchive).where(
                m.MessageArchive.kind == kind,
                m.MessageArchive.entity_id == int(entity_id),
            )
        )

    async def _merge_message_archive(self, kind: str, entity_id: int, items: list[dict]) -> int:
        """Атомарно додає повідомлення у стиснений cold-tier.

        Архів зберігається в тій самій БД: insert/update архіву та delete
        гарячих рядків комітяться однією транзакцією. Тому навіть аварія
        посеред housekeeping не може лишити історію «між двома сховищами».
        """
        if not items:
            return 0
        existing = await self._message_archive(kind, entity_id)
        merged = {}
        if existing is not None:
            for item in _unpack_archive(existing):
                try:
                    merged[int(item.get("id") or 0)] = item
                except (TypeError, ValueError):
                    continue
        for item in items:
            try:
                merged[int(item.get("id") or 0)] = item
            except (TypeError, ValueError):
                continue
        payload_items = [merged[key] for key in sorted(k for k in merged if k > 0)]
        if not payload_items:
            return 0
        ids = [int(x["id"]) for x in payload_items]
        dates = [_archive_parse_dt(x.get("created_at")) for x in payload_items]
        dates = [x for x in dates if x is not None]
        values = {
            "message_count": len(payload_items),
            "raw_bytes": len(_archive_json(payload_items)),
            "min_message_id": min(ids),
            "max_message_id": max(ids),
            "first_at": min(dates) if dates else None,
            "last_at": max(dates) if dates else None,
            "codec": ARCHIVE_CODEC,
            "payload": _pack_archive(payload_items),
        }
        if existing is None:
            self.s.add(m.MessageArchive(kind=kind, entity_id=int(entity_id), **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        return len(items)

    async def archive_cold_messages(self, older_than_days: int = 180, batch: int = 50) -> dict:
        """Стискає історію давно закритих діалогів і прибирає hot rows.

        Це не retention із втратою даних. Повний текст лишається у gzip-json
        cold-tier і прозоро повертається звичайними API читання історії.
        Архівуємо лише прочитані діалоги, щоб unread counters ніколи не
        змінювались через housekeeping.
        """
        days = max(30, int(older_than_days or 180))
        cap = max(1, min(int(batch or 50), 250))
        edge = datetime.now(timezone.utc) - timedelta(days=days)
        result = {"orders": 0, "order_messages": 0, "support_threads": 0, "support_messages": 0}

        unread_order = select(m.OrderMessage.id).where(
            m.OrderMessage.order_id == m.Order.id,
            m.OrderMessage.direction == "in",
            m.OrderMessage.is_read.is_(False),
        ).exists()
        has_order_messages = select(m.OrderMessage.id).where(
            m.OrderMessage.order_id == m.Order.id
        ).exists()
        # CRM background refresh може оновлювати orders.updated_at навіть через
        # роки після продажу. Для CRM-terminal заявки холодний вік рахуємо від
        # business_state_at, інакше така переписка ніколи не стала б archival.
        terminal_at = case(
            (
                and_(
                    m.Order.business_state.in_((business.BUSINESS_SALE, business.BUSINESS_REFUSAL)),
                    m.Order.business_state_at.is_not(None),
                ),
                m.Order.business_state_at,
            ),
            else_=m.Order.updated_at,
        )
        order_ids = list(await self.s.scalars(
            select(m.Order.id)
            .where(
                terminal_at < edge,
                or_(
                    m.Order.status.in_((m.OrderStatus.DONE, m.OrderStatus.CANCELLED)),
                    m.Order.business_state.in_((business.BUSINESS_SALE, business.BUSINESS_REFUSAL)),
                ),
                has_order_messages,
                ~unread_order,
            )
            .order_by(terminal_at, m.Order.id)
            .limit(cap)
        ))
        for order_id in order_ids:
            await self.s.scalar(select(m.Order.id).where(m.Order.id == order_id).with_for_update())
            rows = list(await self.s.scalars(
                select(m.OrderMessage)
                .where(m.OrderMessage.order_id == order_id)
                .order_by(m.OrderMessage.id)
            ))
            if not rows:
                continue
            packed = [_order_message_to_archive(row) for row in rows]
            await self._merge_message_archive("order", order_id, packed)
            existing_refs = set(await self.s.scalars(
                select(m.ArchivedMessageRef.tg_message_id).where(
                    m.ArchivedMessageRef.kind == "order",
                    m.ArchivedMessageRef.entity_id == order_id,
                )
            ))
            for row in rows:
                if row.tg_message_id is None or row.tg_message_id in existing_refs:
                    continue
                self.s.add(m.ArchivedMessageRef(
                    kind="order", entity_id=order_id, user_id=int(row.user_id),
                    tg_message_id=int(row.tg_message_id),
                ))
                existing_refs.add(row.tg_message_id)
            await self.s.execute(delete(m.OrderMessage).where(m.OrderMessage.order_id == order_id))
            result["orders"] += 1
            result["order_messages"] += len(rows)

        remaining = max(0, cap - result["orders"])
        if remaining:
            unread_support = select(m.SupportMessage.id).where(
                m.SupportMessage.thread_id == m.SupportThread.id,
                m.SupportMessage.direction == "in",
                m.SupportMessage.is_read.is_(False),
            ).exists()
            has_support_messages = select(m.SupportMessage.id).where(
                m.SupportMessage.thread_id == m.SupportThread.id
            ).exists()
            thread_ids = list(await self.s.scalars(
                select(m.SupportThread.id)
                .where(
                    m.SupportThread.status == "closed",
                    m.SupportThread.closed_at.is_not(None),
                    m.SupportThread.closed_at < edge,
                    has_support_messages,
                    ~unread_support,
                )
                .order_by(m.SupportThread.closed_at, m.SupportThread.id)
                .limit(remaining)
            ))
            for thread_id in thread_ids:
                rows = list(await self.s.scalars(
                    select(m.SupportMessage)
                    .where(m.SupportMessage.thread_id == thread_id)
                    .order_by(m.SupportMessage.id)
                ))
                if not rows:
                    continue
                packed = [_support_message_to_archive(row) for row in rows]
                await self._merge_message_archive("support", thread_id, packed)
                await self.s.execute(delete(m.SupportMessage).where(m.SupportMessage.thread_id == thread_id))
                result["support_threads"] += 1
                result["support_messages"] += len(rows)

        if result["order_messages"] or result["support_messages"]:
            await self.s.commit()
        return result

    async def prune_expired_tokens(self, now, *, batch=1000, max_batches=20):
        removed = {}
        for name, model in (("dashboard_sessions", m.DashboardSession),):
            total = 0
            for _ in range(max_batches):
                ids = select(model.id).where(model.expires_at <= now).limit(batch).scalar_subquery()
                result = await self.s.execute(delete(model).where(model.id.in_(ids))
                                              .execution_options(synchronize_session=False))
                await self.s.commit()
                total += int(result.rowcount or 0)
                if (result.rowcount or 0) < batch:
                    break
            removed[name] = total
        return removed

    async def prune_panel_notifications(self, older_than_days: int = 90) -> int:
        """Видаляє лише оперативні panel notifications, не бізнес-історію."""
        days = max(7, int(older_than_days or 90))
        edge = datetime.now(timezone.utc) - timedelta(days=days)
        stale_ids = select(m.PanelNotification.id).where(m.PanelNotification.created_at < edge)
        # SQLite у локальних/QA запусках може працювати без FK cascade, тому
        # read-маркери чистимо явно. PostgreSQL виконає той самий запит дешево
        # через індекс notification_id.
        await self.s.execute(
            delete(m.PanelNotificationRead).where(
                m.PanelNotificationRead.notification_id.in_(stale_ids)
            )
        )
        result = await self.s.execute(
            delete(m.PanelNotification).where(m.PanelNotification.created_at < edge)
        )
        removed = int(result.rowcount or 0)
        if removed:
            await self.s.commit()
        return removed
