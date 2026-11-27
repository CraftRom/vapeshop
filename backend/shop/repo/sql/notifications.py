from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class NotificationsMixin:
    @staticmethod
    def _panel_notification_dict(row, *, read: bool = False) -> dict:
        return {
            "id": row.id,
            "kind": row.kind,
            "title": row.title,
            "body": row.body or "",
            "href": row.href,
            "entity_id": row.entity_id,
            "actor": row.actor,
            "created_at": row.created_at,
            "read": bool(read),
        }

    async def create_panel_notification(self, data: dict) -> dict:
        row = m.PanelNotification(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)

        # Retention виконує добовий housekeeping, а не кожне створення події:
        # DELETE по великій таблиці в hot-path нового замовлення/повідомлення
        # створював зайві записи WAL і contention без жодної користі.
        return self._panel_notification_dict(row)

    async def _panel_read_cursor(self, viewer_key: str) -> int:
        row = await self.s.get(m.PanelNotificationCursor, viewer_key)
        return int(row.through_id or 0) if row else 0

    async def list_panel_notifications(
        self, viewer_key: str, *, limit: int = 60, after_id: int | None = None
    ) -> list[dict]:
        if after_id is None:
            await self._prune_orphan_panel_notifications()
        stmt = select(m.PanelNotification)
        if after_id is not None:
            stmt = stmt.where(m.PanelNotification.id > int(after_id))
        rows = list(await self.s.scalars(
            stmt.order_by(m.PanelNotification.id.desc()).limit(max(1, min(int(limit), 200)))
        ))
        if not rows:
            return []
        cursor = await self._panel_read_cursor(viewer_key)
        ids = [row.id for row in rows if row.id > cursor]
        explicit = set()
        if ids:
            explicit = set(await self.s.scalars(
                select(m.PanelNotificationRead.notification_id).where(
                    m.PanelNotificationRead.viewer_key == viewer_key,
                    m.PanelNotificationRead.notification_id.in_(ids),
                )
            ))
        return [
            self._panel_notification_dict(row, read=(row.id <= cursor or row.id in explicit))
            for row in rows
        ]

    async def panel_notification_unread_count(self, viewer_key: str) -> int:
        cursor = await self._panel_read_cursor(viewer_key)
        total = int(await self.s.scalar(
            select(func.count(m.PanelNotification.id)).where(m.PanelNotification.id > cursor)
        ) or 0)
        if not total:
            return 0
        read = int(await self.s.scalar(
            select(func.count(m.PanelNotificationRead.id)).where(
                m.PanelNotificationRead.viewer_key == viewer_key,
                m.PanelNotificationRead.notification_id > cursor,
            )
        ) or 0)
        return max(0, total - read)

    async def mark_panel_notification_read(self, notification_id: int, viewer_key: str) -> bool:
        exists_row = await self.s.scalar(
            select(m.PanelNotification.id).where(m.PanelNotification.id == notification_id)
        )
        if exists_row is None:
            return False
        cursor = await self._panel_read_cursor(viewer_key)
        if int(notification_id) <= cursor:
            return True
        already = await self.s.scalar(
            select(m.PanelNotificationRead.id).where(
                m.PanelNotificationRead.notification_id == notification_id,
                m.PanelNotificationRead.viewer_key == viewer_key,
            )
        )
        if already is None:
            self.s.add(m.PanelNotificationRead(
                notification_id=notification_id, viewer_key=viewer_key
            ))
            try:
                await self.s.commit()
            except IntegrityError:
                await self.s.rollback()
        return True

    async def mark_all_panel_notifications_read(self, viewer_key: str) -> int:
        """O(1) read-all via cursor instead of one DB row per notification."""
        changed = await self.panel_notification_unread_count(viewer_key)
        latest = int(await self.s.scalar(select(func.max(m.PanelNotification.id))) or 0)
        if not latest:
            return 0
        row = await self.s.get(m.PanelNotificationCursor, viewer_key)
        if row is None:
            row = m.PanelNotificationCursor(viewer_key=viewer_key, through_id=latest)
            self.s.add(row)
        elif int(row.through_id or 0) < latest:
            row.through_id = latest
        # Точкові read-маркери до курсора вже повністю описані одним числом.
        await self.s.execute(
            delete(m.PanelNotificationRead).where(
                m.PanelNotificationRead.viewer_key == viewer_key,
                m.PanelNotificationRead.notification_id <= latest,
            )
        )
        await self.s.commit()
        return changed

    async def create_dashboard_session(self, data: dict) -> None:
        await self.s.execute(delete(m.DashboardSession).where(m.DashboardSession.expires_at <= data["created_at"]))
        self.s.add(m.DashboardSession(**data))
        await self.s.commit()

    async def get_dashboard_session(self, digest: str) -> dict | None:
        row = await self.s.get(m.DashboardSession, digest)
        return {c.name: getattr(row, c.name) for c in m.DashboardSession.__table__.columns} if row else None

    async def delete_dashboard_session(self, digest: str) -> None:
        await self.s.execute(delete(m.DashboardSession).where(m.DashboardSession.id == digest))
        await self.s.commit()

    async def touch_dashboard_session(self, digest: str, now: datetime) -> None:
        await self.s.execute(update(m.DashboardSession).where(m.DashboardSession.id == digest).values(last_seen_at=now))
        await self.s.commit()
