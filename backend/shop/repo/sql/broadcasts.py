from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class BroadcastsMixin:
    async def list_broadcasts(self) -> list[Broadcast]:
        return [_broadcast(r) for r in await self.s.scalars(
            select(m.Broadcast).order_by(m.Broadcast.created_at.desc())
        )]

    async def get_broadcast(self, broadcast_id) -> Broadcast | None:
        return _broadcast(await self.s.get(m.Broadcast, broadcast_id, populate_existing=True))

    async def get_broadcast_by_client_key(self, client_key):
        return _broadcast(await self.s.scalar(select(m.Broadcast).where(m.Broadcast.client_key == client_key)))

    async def media_references(self, url):
        result = {}
        for label, model in [('products', m.Product), ('broadcasts', m.Broadcast)]:
            result[label] = int(await self.s.scalar(select(func.count()).select_from(model).where(
                or_(model.photo_url == url, model.photo_url.endswith(url, autoescape=True))
            )) or 0)
        return result

    async def create_broadcast(self, data: dict) -> Broadcast:
        row = m.Broadcast(**data)
        self.s.add(row)
        try:
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            existing = await self.get_broadcast_by_client_key(data['client_key']) if data.get('client_key') else None
            if existing:
                return existing
            raise
        await self.s.refresh(row)
        return _broadcast(row)

    async def update_broadcast(self, broadcast_id, data: dict) -> Broadcast | None:
        row = await self.s.get(m.Broadcast, broadcast_id)
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        return _broadcast(row)

    async def transition_broadcast(self, broadcast_id, statuses, data) -> bool:
        result = await self.s.execute(update(m.Broadcast).where(
            m.Broadcast.id == broadcast_id, m.Broadcast.status.in_(statuses)
        ).values(**data).execution_options(synchronize_session=False))
        await self.s.commit()
        return result.rowcount == 1

    async def claim_broadcast(self, broadcast_id, owner, lease_seconds=120) -> Broadcast | None:
        now = datetime.now(timezone.utc)
        result = await self.s.execute(update(m.Broadcast).where(
            m.Broadcast.id == broadcast_id,
            or_(m.Broadcast.status == BroadcastStatus.SENDING,
                and_(m.Broadcast.status == BroadcastStatus.SCHEDULED,
                     m.Broadcast.scheduled_at <= now)),
            or_(m.Broadcast.lease_until.is_(None), m.Broadcast.lease_until <= now),
        ).values(status=BroadcastStatus.SENDING, lease_owner=owner,
                 lease_until=now + timedelta(seconds=lease_seconds), heartbeat_at=now)
          .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            await self.s.rollback()
            return None
        # A previous process may have sent these. Never retry an ambiguous attempt.
        recovered = await self.s.execute(update(m.BroadcastDelivery).where(
            m.BroadcastDelivery.broadcast_id == broadcast_id,
            m.BroadcastDelivery.status == "sending",
        ).values(status="unknown", error="Виконавець зупинився до збереження результату",
                 updated_at=now).execution_options(synchronize_session=False))
        if recovered.rowcount:
            await self.s.execute(update(m.Broadcast).where(m.Broadcast.id == broadcast_id)
                .values(unknown_count=m.Broadcast.unknown_count + recovered.rowcount)
                .execution_options(synchronize_session=False))
        await self.s.commit()
        return await self.get_broadcast(broadcast_id)

    async def _broadcast_guard(self, broadcast_id, owner, **values) -> bool:
        # Conditional UPDATE also locks the parent row until journal/counter commit.
        now = datetime.now(timezone.utc)
        result = await self.s.execute(update(m.Broadcast).where(
            m.Broadcast.id == broadcast_id, m.Broadcast.status == BroadcastStatus.SENDING,
            m.Broadcast.lease_owner == owner, m.Broadcast.lease_until > now,
        ).values(**(values or {"heartbeat_at": now}))
          .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            await self.s.rollback()
            return False
        return True

    async def heartbeat_broadcast(self, broadcast_id, owner, lease_seconds=120) -> bool:
        now = datetime.now(timezone.utc)
        ok = await self._broadcast_guard(broadcast_id, owner, heartbeat_at=now,
                                        lease_until=now + timedelta(seconds=lease_seconds))
        if ok:
            await self.s.commit()
        return ok

    async def begin_broadcast_delivery(self, broadcast_id, owner, user_id, tg_id) -> dict:
        if not await self._broadcast_guard(broadcast_id, owner):
            return {"action": "lost"}
        row = await self.s.get(m.BroadcastDelivery, (broadcast_id, user_id), populate_existing=True)
        now = datetime.now(timezone.utc)
        if row and row.status in ("sent", "failed", "unknown"):
            await self.s.commit()
            return {"action": "skip"}
        if row and row.next_attempt_at:
            due = row.next_attempt_at.replace(tzinfo=timezone.utc) if row.next_attempt_at.tzinfo is None else row.next_attempt_at
            if due > now:
                await self.s.commit()
                return {"action": "wait", "next_attempt_at": due}
        if row is None:
            row = m.BroadcastDelivery(broadcast_id=broadcast_id, user_id=user_id,
                                      tg_id=tg_id, attempts=0)
            self.s.add(row)
        row.status = "sending"
        row.attempts += 1
        row.next_attempt_at = None
        row.updated_at = now
        await self.s.commit()  # MUST precede network I/O
        return {"action": "send", "attempts": row.attempts}

    async def finish_broadcast_delivery(self, broadcast_id, owner, user_id, status, error=None, next_attempt_at=None) -> bool:
        if status not in ("sent", "failed", "unknown", "retry"):
            raise ValueError("invalid delivery result")
        if not await self._broadcast_guard(broadcast_id, owner):
            return False
        row = await self.s.get(m.BroadcastDelivery, (broadcast_id, user_id), populate_existing=True)
        if row is None or row.status != "sending":
            await self.s.rollback()
            return False
        row.status, row.error = status, error
        row.next_attempt_at = next_attempt_at
        row.updated_at = datetime.now(timezone.utc)
        values = {"last_error": error} if error else {}
        count = {"sent": "sent_count", "failed": "failed_count", "unknown": "unknown_count"}.get(status)
        if count:
            values[count] = getattr(m.Broadcast, count) + 1
        if values:
            await self.s.execute(update(m.Broadcast).where(m.Broadcast.id == broadcast_id)
                .values(**values).execution_options(synchronize_session=False))
        await self.s.commit()
        return True

    async def release_broadcast(self, broadcast_id, owner, *, cursor_id=None, finished=False, error=None, next_attempt_at=None) -> bool:
        values = {"lease_owner": None, "lease_until": next_attempt_at}
        if cursor_id is not None:
            values["cursor_id"] = cursor_id
        if finished:
            values.update(status=BroadcastStatus.SENT, finished_at=datetime.now(timezone.utc))
        if error:
            values["last_error"] = error
        ok = await self._broadcast_guard(broadcast_id, owner, **values)
        if ok:
            await self.s.commit()
        return ok

    async def list_broadcast_deliveries(self, broadcast_id, after=0, limit=100) -> dict:
        rows = list(await self.s.scalars(select(m.BroadcastDelivery).where(
            m.BroadcastDelivery.broadcast_id == broadcast_id, m.BroadcastDelivery.user_id > after
        ).order_by(m.BroadcastDelivery.user_id).limit(limit + 1)))
        return {"items": [{"user_id": r.user_id, "tg_id": r.tg_id, "status": r.status,
                           "attempts": r.attempts, "error": r.error,
                           "next_attempt_at": r.next_attempt_at, "updated_at": r.updated_at}
                          for r in rows[:limit]],
                "next_cursor": rows[limit - 1].user_id if len(rows) > limit else None}

    async def delete_order(self, order_id) -> bool:
        # Позиції й повідомлення прибираємо явно, а не покладаємось на
        # каскад: він налаштований не на всіх звʼязках, і мовчазні сироти
        # в базі гірші за зайвий запит.
        await self.s.execute(delete(m.OrderItem).where(m.OrderItem.order_id == order_id))
        await self.s.execute(
            delete(m.OrderMessage).where(m.OrderMessage.order_id == order_id))
        await self.s.execute(
            delete(m.MessageArchive).where(
                m.MessageArchive.kind == "order", m.MessageArchive.entity_id == order_id
            )
        )
        await self.s.execute(
            delete(m.ArchivedMessageRef).where(
                m.ArchivedMessageRef.kind == "order", m.ArchivedMessageRef.entity_id == order_id
            )
        )
        await self._delete_panel_notifications_for_entity(
            ("order.created", "order.message"), order_id
        )
        result = await self.s.execute(delete(m.Order).where(m.Order.id == order_id))
        await self.s.commit()
        return result.rowcount > 0

    async def delete_all_orders(self) -> int:
        count = (await self.s.execute(select(func.count()).select_from(m.Order))).scalar_one()
        await self.s.execute(delete(m.OrderItem))
        await self.s.execute(delete(m.OrderMessage))
        await self.s.execute(
            delete(m.MessageArchive).where(m.MessageArchive.kind == "order")
        )
        await self.s.execute(
            delete(m.ArchivedMessageRef).where(m.ArchivedMessageRef.kind == "order")
        )
        notification_ids = list(await self.s.scalars(
            select(m.PanelNotification.id).where(
                m.PanelNotification.kind.in_(("order.created", "order.message"))
            )
        ))
        if notification_ids:
            await self.s.execute(
                delete(m.PanelNotificationRead).where(
                    m.PanelNotificationRead.notification_id.in_(notification_ids)
                )
            )
            await self.s.execute(
                delete(m.PanelNotification).where(m.PanelNotification.id.in_(notification_ids))
            )
        await self.s.execute(delete(m.Order))
        # Підсумки клієнтів обнуляємо разом із замовленнями: інакше в
        # картці клієнта лишиться «12 замовлень», яких більше немає.
        await self.s.execute(update(m.User).values(orders_count=0, total_spent=0))
        await self.s.commit()
        return int(count)

    async def delete_broadcast(self, broadcast_id) -> bool:
        # Lock and re-check atomically against concurrent send/scheduler claims.
        result = await self.s.execute(update(m.Broadcast).where(
            m.Broadcast.id == broadcast_id, m.Broadcast.status != BroadcastStatus.SENDING
        ).values(last_error=m.Broadcast.last_error).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            await self.s.rollback()
            return False
        await self.s.execute(delete(m.BroadcastDelivery).where(m.BroadcastDelivery.broadcast_id == broadcast_id))
        await self.s.execute(delete(m.Broadcast).where(m.Broadcast.id == broadcast_id))
        await self.s.commit()
        return True

    async def next_pending_broadcast(self) -> Broadcast | None:
        due = await self.due_broadcasts(datetime.now(timezone.utc))
        return next((b for b in due if b.status == BroadcastStatus.SENDING), None)

    async def due_broadcasts(self, now: datetime) -> list[Broadcast]:
        rows = await self.s.scalars(select(m.Broadcast).where(
            or_(and_(m.Broadcast.status == BroadcastStatus.SCHEDULED, m.Broadcast.scheduled_at <= now),
                and_(m.Broadcast.status == BroadcastStatus.SENDING,
                     or_(m.Broadcast.lease_until.is_(None), m.Broadcast.lease_until <= now)))
        ).order_by(m.Broadcast.created_at).limit(100))
        return [_broadcast(row) for row in rows]

    # --------------------------------------------------------- segments

    def _segment_query(self, segment: dict):
        stype = (segment or {}).get("type", "all")
        base = select(m.User).where(
            m.User.is_blocked.is_(False), m.User.age_confirmed.is_(True)
        )
        if stype == "with_orders":
            return base.where(m.User.orders_count > 0)
        if stype == "no_orders":
            return base.where(m.User.orders_count == 0)
        if stype == "inactive":
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(segment.get("days", 30)))
            return base.where(m.User.last_seen_at < cutoff)
        if stype == "top_spenders":
            return base.where(m.User.total_spent >= float(segment.get("min_total", 1000)))
        if stype == "with_referrals":
            return base.where(m.User.referrals_count > 0)
        return base

    async def count_segment(self, segment: dict) -> int:
        query = self._segment_query(segment).with_only_columns(
            func.count(m.User.id)
        ).order_by(None)
        return await self.s.scalar(query) or 0

    async def segment_recipients(self, segment, cursor_id, limit):
        query = (
            self._segment_query(segment)
            .with_only_columns(m.User.id, m.User.tg_id)
            .where(m.User.id > cursor_id).order_by(m.User.id).limit(limit)
        )
        return [(row[0], row[1]) for row in await self.s.execute(query)]
