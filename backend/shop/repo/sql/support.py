from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class SupportMixin:
    async def ensure_support_thread(self, user_id: int) -> SupportThread:
        """Повертає поточну відкриту сесію або створює нову.

        Цей метод викликається тільки явним входом у /ask. Закриті сесії
        не перевідкриваються. Частковий UNIQUE-індекс захищає від двох
        паралельних /ask для одного клієнта.
        """
        row = await self.s.scalar(
            select(m.SupportThread)
            .where(
                m.SupportThread.user_id == user_id,
                m.SupportThread.status == "open",
            )
            .order_by(m.SupportThread.updated_at.desc(), m.SupportThread.id.desc())
        )
        if row is not None:
            return _support_thread(row)

        now = datetime.now(timezone.utc)
        row = m.SupportThread(
            user_id=user_id,
            status="open",
            updated_at=now,
            last_message_at=now,
            closed_at=None,
            closed_by=None,
            closed_by_name=None,
            close_reason=None,
        )
        self.s.add(row)
        try:
            await self.s.commit()
        except IntegrityError:
            # Два /ask могли прийти майже одночасно. База лишає рівно одну
            # відкриту сесію; другий запит після rollback просто бере її.
            await self.s.rollback()
            existing = await self.s.scalar(
                select(m.SupportThread)
                .where(
                    m.SupportThread.user_id == user_id,
                    m.SupportThread.status == "open",
                )
                .order_by(m.SupportThread.updated_at.desc(), m.SupportThread.id.desc())
            )
            if existing is None:
                raise
            return _support_thread(existing)
        await self.s.refresh(row)
        return _support_thread(row)

    async def get_support_thread(self, thread_id: int) -> SupportThread | None:
        row = await self.s.scalar(
            select(m.SupportThread)
            .options(selectinload(m.SupportThread.user))
            .where(m.SupportThread.id == thread_id)
        )
        if not row:
            return None
        unread = await self.s.scalar(
            select(func.count(m.SupportMessage.id)).where(
                m.SupportMessage.thread_id == thread_id,
                m.SupportMessage.direction == "in",
                m.SupportMessage.is_read.is_(False),
            )
        )
        return _support_thread(row, unread_count=int(unread or 0), with_user=True)

    async def get_support_thread_for_user(self, user_id: int) -> SupportThread | None:
        """Повертає тільки активну сесію; закрита ніколи не оживає сама."""
        row = await self.s.scalar(
            select(m.SupportThread)
            .options(selectinload(m.SupportThread.user))
            .where(
                m.SupportThread.user_id == user_id,
                m.SupportThread.status == "open",
            )
            .order_by(m.SupportThread.updated_at.desc(), m.SupportThread.id.desc())
        )
        return _support_thread(row, with_user=True) if row else None

    async def list_support_threads(self, status: str | None = None) -> list[SupportThread]:
        stmt = (
            select(m.SupportThread)
            .options(selectinload(m.SupportThread.user))
            .order_by(
                m.SupportThread.last_message_at.desc().nullslast(),
                m.SupportThread.updated_at.desc(),
                m.SupportThread.id.desc(),
            )
        )
        if status in {"open", "closed"}:
            stmt = stmt.where(m.SupportThread.status == status)
        rows = list(await self.s.scalars(stmt))
        if not rows:
            return []
        ids = [row.id for row in rows]
        counts = {
            int(thread_id): int(count)
            for thread_id, count in (await self.s.execute(
                select(m.SupportMessage.thread_id, func.count(m.SupportMessage.id))
                .where(
                    m.SupportMessage.thread_id.in_(ids),
                    m.SupportMessage.direction == "in",
                    m.SupportMessage.is_read.is_(False),
                )
                .group_by(m.SupportMessage.thread_id)
            )).all()
        }
        return [
            _support_thread(row, unread_count=counts.get(row.id, 0), with_user=True)
            for row in rows
        ]

    async def close_support_thread(
        self,
        thread_id: int,
        *,
        closed_by: str,
        closed_by_name: str = "",
        close_reason: str = "",
    ) -> tuple[SupportThread | None, bool]:
        """Закриває конкретну сесію рівно один раз.

        Рядок блокується до commit. Якщо повідомлення вже почало запис у
        відкриту сесію, воно завершиться перед закриттям; якщо закриття
        виграло гонку — нове повідомлення в цю сесію вже не потрапить.
        """
        row = await self.s.scalar(
            select(m.SupportThread)
            .where(m.SupportThread.id == thread_id)
            .with_for_update()
        )
        if row is None:
            await self.s.commit()
            return None, False
        if row.status == "closed":
            await self.s.commit()
            return await self.get_support_thread(thread_id), False

        now = datetime.now(timezone.utc)
        row.status = "closed"
        row.closed_at = now
        row.closed_by = (closed_by or "system")[:16]
        row.closed_by_name = (closed_by_name or "")[:128] or None
        row.close_reason = (close_reason or "")[:32] or None
        row.updated_at = now
        await self.s.commit()
        return await self.get_support_thread(thread_id), True

    async def add_support_message(self, data: dict) -> SupportMessage:
        """Низькорівнева вставка без перевірки статусу.

        Лишається для міграцій/тестів. Робочі клієнтські та операторські
        повідомлення повинні йти через add_support_message_if_open().
        """
        row = m.SupportMessage(**data)
        self.s.add(row)
        await self.s.flush()
        now = row.created_at or datetime.now(timezone.utc)
        await self.s.execute(
            update(m.SupportThread)
            .where(m.SupportThread.id == row.thread_id)
            .values(last_message_at=now, updated_at=now)
        )
        await self.s.commit()
        await self.s.refresh(row)
        return _support_message(row)

    async def add_support_message_if_open(self, data: dict) -> SupportMessage | None:
        """Атомарно перевіряє сесію й додає повідомлення тільки у open."""
        thread_id = int(data["thread_id"])
        thread = await self.s.scalar(
            select(m.SupportThread)
            .where(
                m.SupportThread.id == thread_id,
                m.SupportThread.status == "open",
            )
            .with_for_update()
        )
        if thread is None:
            await self.s.commit()
            return None

        row = m.SupportMessage(**data)
        self.s.add(row)
        await self.s.flush()
        now = row.created_at or datetime.now(timezone.utc)
        thread.last_message_at = now
        thread.updated_at = now
        await self.s.commit()
        await self.s.refresh(row)
        return _support_message(row)

    async def list_support_messages(self, thread_id: int, limit: int = 300) -> list[SupportMessage]:
        cap = max(1, min(int(limit or 300), 1000))
        archive = await self._message_archive("support", int(thread_id))
        archived = [_archived_support_message(x) for x in _unpack_archive(archive)]
        archived = [x for x in archived if x.id > 0]
        rows = list(await self.s.scalars(
            select(m.SupportMessage)
            .where(m.SupportMessage.thread_id == thread_id)
            .order_by(m.SupportMessage.id.desc())
            .limit(cap)
        ))
        live = [_support_message(row) for row in rows]
        merged = {x.id: x for x in [*archived, *live]}
        return [merged[k] for k in sorted(merged)[-cap:]]

    async def recent_support_messages(self, thread_id: int, limit: int = 24) -> list[SupportMessage]:
        """Останні hot-повідомлення без читання всього архіву.

        Використовується лише для FAQ context gating. Відкриті support-thread
        не архівуються lifecycle-процесом, тож останні репліки гарантовано hot.
        """
        cap = max(1, min(int(limit or 24), 100))
        rows = list(await self.s.scalars(
            select(m.SupportMessage)
            .where(m.SupportMessage.thread_id == int(thread_id))
            .order_by(m.SupportMessage.id.desc())
            .limit(cap)
        ))
        rows.reverse()
        return [_support_message(row) for row in rows]

    async def get_support_message(self, thread_id, message_id):
        row = await self.s.scalar(select(m.SupportMessage).where(
            m.SupportMessage.thread_id == thread_id, m.SupportMessage.id == message_id))
        if row is not None:
            return _support_message(row)
        archive = await self._message_archive("support", int(thread_id))
        item = next((x for x in _unpack_archive(archive) if x.get("id") == message_id), None)
        return _archived_support_message(item) if item else None

    async def list_user_support_threads(self, user_id, before_id=None, limit=20):
        stmt = select(m.SupportThread).where(m.SupportThread.user_id == user_id)
        if before_id is not None:
            stmt = stmt.where(m.SupportThread.id < before_id)
        rows = await self.s.scalars(stmt.order_by(m.SupportThread.id.desc()).limit(limit))
        return [_support_thread(row) for row in rows]

    async def page_support_messages(self, thread_id, before_id=None, after_id=None, limit=200):
        cap = max(1, min(int(limit), 200))
        archive = await self._message_archive("support", int(thread_id))
        archived = [_archived_support_message(x) for x in _unpack_archive(archive)]
        stmt = select(m.SupportMessage).where(m.SupportMessage.thread_id == thread_id)
        if before_id is not None:
            stmt = stmt.where(m.SupportMessage.id < before_id)
            archived = [x for x in archived if x.id < before_id]
        if after_id is not None:
            stmt = stmt.where(m.SupportMessage.id > after_id)
            archived = [x for x in archived if x.id > after_id]
        stmt = stmt.order_by(m.SupportMessage.id.asc() if after_id is not None else m.SupportMessage.id.desc()).limit(cap)
        live = [_support_message(row) for row in await self.s.scalars(stmt)]
        merged = {x.id: x for x in [*archived, *live] if x.id > 0}
        ids = sorted(merged)
        ids = ids[:cap] if after_id is not None else ids[-cap:]
        return [merged[key] for key in ids]

    async def add_support_client_message(self, thread_id, user, text, request_id):
        # Both ownership and open-state are checked while holding the same row
        # lock used by staff/client close. A replay never reopens a closed chat.
        thread = await self.s.scalar(select(m.SupportThread).where(
            m.SupportThread.id == thread_id, m.SupportThread.user_id == user.id).with_for_update())
        if thread is None:
            return None
        async def replay():
            row = await self.s.scalar(select(m.SupportMessage).where(
                m.SupportMessage.thread_id == thread_id, m.SupportMessage.client_request_id == request_id))
            if row is None:
                return None
            if row.text != text or row.user_id != user.id:
                raise ValueError("Ключ повідомлення вже використано для іншого тексту")
            result = _support_message(row)
            result.client_replayed = True
            return result
        existing = await replay()
        if existing is not None:
            await self.s.commit()
            return existing
        if thread.status != "open":
            await self.s.commit()
            return None
        row = m.SupportMessage(thread_id=thread_id, user_id=user.id, direction="in",
            author=user.first_name or user.username or f"id{user.tg_id}", text=text,
            is_read=False, client_request_id=request_id)
        self.s.add(row)
        try:
            await self.s.flush()
            thread.last_message_at = row.created_at or datetime.now(timezone.utc)
            thread.updated_at = thread.last_message_at
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            existing = await replay()
            if existing is None:
                raise
            return existing
        await self.s.refresh(row)
        return _support_message(row)

    async def mark_support_message_ids_read(self, thread_id, message_ids):
        ids = {int(x) for x in (message_ids or []) if 0 < int(x) <= 2147483647}
        if not ids:
            return 0
        result = await self.s.execute(update(m.SupportMessage).where(
            m.SupportMessage.thread_id == thread_id, m.SupportMessage.id.in_(ids),
            m.SupportMessage.direction == "in", m.SupportMessage.is_read.is_(False),
        ).values(is_read=True))
        # Cold archives normally contain only read messages. Keep ACK correct
        # for older imported archives too, without affecting other sessions.
        archive = await self.s.scalar(select(m.MessageArchive).where(
            m.MessageArchive.kind == 'support', m.MessageArchive.entity_id == int(thread_id),
        ).with_for_update())
        items = _unpack_archive(archive)
        changed = int(result.rowcount or 0)
        cold_changed = 0
        for item in items:
            if int(item.get("id") or 0) in ids and item.get("direction") == "in" and not item.get("is_read"):
                item["is_read"] = True
                changed += 1
                cold_changed += 1
        if cold_changed and archive:
            archive.payload = _pack_archive(items)
            archive.raw_bytes = len(_archive_json(items))
        await self._commit()
        return changed

    async def mark_support_read(self, thread_id: int) -> int:
        result = await self.s.execute(
            update(m.SupportMessage)
            .where(
                m.SupportMessage.thread_id == thread_id,
                m.SupportMessage.direction == "in",
                m.SupportMessage.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self._commit()
        return int(result.rowcount or 0)

    async def support_unread_count(self) -> int:
        count = await self.s.scalar(
            select(func.count(m.SupportMessage.id)).where(
                m.SupportMessage.direction == "in",
                m.SupportMessage.is_read.is_(False),
            )
        )
        return int(count or 0)

    async def support_stats(self) -> dict[str, int]:
        open_count = await self.s.scalar(
            select(func.count(m.SupportThread.id)).where(m.SupportThread.status == "open")
        )
        closed_count = await self.s.scalar(
            select(func.count(m.SupportThread.id)).where(m.SupportThread.status == "closed")
        )
        clients = await self.s.scalar(
            select(func.count(func.distinct(m.SupportThread.user_id)))
        )
        unread = await self.support_unread_count()
        return {
            "open": int(open_count or 0),
            "closed": int(closed_count or 0),
            "total": int(open_count or 0) + int(closed_count or 0),
            "clients": int(clients or 0),
            "unread": int(unread or 0),
        }

    async def delete_support_thread(self, thread_id: int) -> bool:
        """Явне ручне видалення. Закриття саме по собі нічого не стирає."""
        row = await self.s.get(m.SupportThread, thread_id)
        if not row:
            return False
        await self._delete_panel_notifications_for_entity(("support.message",), thread_id)
        await self.s.execute(
            delete(m.MessageArchive).where(
                m.MessageArchive.kind == "support", m.MessageArchive.entity_id == thread_id
            )
        )
        await self.s.delete(row)
        await self.s.commit()
        return True
