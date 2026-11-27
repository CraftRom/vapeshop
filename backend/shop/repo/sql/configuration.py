from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class ConfigurationMixin:
    async def get_settings_map(self) -> dict[str, str]:
        rows = await self.s.execute(select(m.Setting.key, m.Setting.value))
        return {key: value for key, value in rows}

    async def save_settings_map(self, values: dict[str, str]) -> None:
        existing = {key for (key,) in await self.s.execute(select(m.Setting.key))}
        for key, value in values.items():
            if key in existing:
                await self.s.execute(
                    update(m.Setting).where(m.Setting.key == key).values(value=str(value))
                )
            else:
                self.s.add(m.Setting(key=key, value=str(value)))
        await self._commit()

    # ------------------------------------------------ квитанції імпорту

    async def claim_catalog_import(self, digest, actor, *, forget_before, mode="", prices="",
                                   payload=None, total=0):
        await self.s.execute(delete(m.CatalogImport).where(
            m.CatalogImport.created_at < forget_before, m.CatalogImport.status.in_(("done", "failed"))))
        self.s.add(m.CatalogImport(digest=digest, status="queued", actor=(actor or "")[:64], result="",
                                   created_at=datetime.now(timezone.utc), mode=mode, prices=prices,
                                   payload=payload, rows_total=int(total), rows_done=0, attempts=0))
        try:
            await self._commit()
            return None
        except IntegrityError:
            await self.s.rollback()
        return await self.get_import_job(digest) or {"status": "queued", "result": None, "created_at": None}

    async def get_import_job(self, digest):
        row = await self.s.get(m.CatalogImport, digest, populate_existing=True)
        if row is None:
            return None
        return {"id": row.digest, "status": row.status, "created_at": _aware(row.created_at),
                "finished_at": _aware(row.finished_at) if row.finished_at else None,
                "rows_total": row.rows_total, "rows_done": row.rows_done, "attempts": row.attempts,
                "mode": row.mode, "prices": row.prices, "actor": row.actor, "error": row.error or "",
                "result": json.loads(row.result) if row.result else None}

    async def import_job_rows(self, digest):
        payload = await self.s.scalar(select(m.CatalogImport.payload).where(m.CatalogImport.digest == digest))
        return json.loads(payload) if payload else None

    async def next_import_job(self, now, *, max_attempts=3):
        return await self.s.scalar(select(m.CatalogImport.digest).where(
            m.CatalogImport.attempts < max_attempts,
            or_(m.CatalogImport.status == "queued",
                and_(m.CatalogImport.status == "running", m.CatalogImport.lease_until < now)))
            .order_by(m.CatalogImport.created_at, m.CatalogImport.digest).limit(1))

    async def lease_import_job(self, digest, owner, *, now, lease_until, max_attempts=3):
        result = await self.s.execute(update(m.CatalogImport).where(
            m.CatalogImport.digest == digest, m.CatalogImport.attempts < max_attempts,
            or_(m.CatalogImport.status == "queued",
                and_(m.CatalogImport.status == "running", m.CatalogImport.lease_until < now))
        ).values(status="running", lease_owner=owner[:64], lease_until=lease_until,
                 attempts=m.CatalogImport.attempts + 1).execution_options(synchronize_session=False))
        await self._commit()
        return result.rowcount == 1

    async def checkpoint_import_job(self, digest, owner, *, rows_done, partial, lease_until):
        """Fenced: a worker whose lease was taken over can no longer write."""
        result = await self.s.execute(update(m.CatalogImport).where(
            m.CatalogImport.digest == digest, m.CatalogImport.status == "running",
            m.CatalogImport.lease_owner == owner[:64]
        ).values(rows_done=rows_done, lease_until=lease_until,
                 result=json.dumps(partial, ensure_ascii=False, default=str))
         .execution_options(synchronize_session=False))
        await self._commit()
        return result.rowcount == 1

    async def finish_catalog_import(self, digest, result, *, owner=None):
        condition = [m.CatalogImport.digest == digest]
        if owner is not None:
            condition += [m.CatalogImport.status == "running", m.CatalogImport.lease_owner == owner[:64]]
        done = await self.s.execute(update(m.CatalogImport).where(*condition).values(
            status="done", result=json.dumps(result, ensure_ascii=False, default=str), payload=None,
            rows_done=m.CatalogImport.rows_total, lease_until=None, finished_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False))
        await self._commit()
        return done.rowcount == 1

    async def fail_import_job(self, digest, owner, error, *, max_attempts=3):
        row = await self.s.get(m.CatalogImport, digest, populate_existing=True)
        if row is None or row.lease_owner != owner[:64] or row.status != "running":
            return None
        final = row.attempts >= max_attempts
        await self.s.execute(update(m.CatalogImport).where(m.CatalogImport.digest == digest).values(
            status="failed" if final else "queued", error=str(error)[:500], lease_until=None,
            payload=None if final else row.payload,
            finished_at=datetime.now(timezone.utc) if final else None).execution_options(synchronize_session=False))
        await self._commit()
        return "failed" if final else "queued"

    async def forget_catalog_import(self, digest, *, only_done=False):
        condition = [m.CatalogImport.digest == digest]
        if only_done:
            condition.append(m.CatalogImport.status.in_(("done", "failed")))
        await self.s.execute(delete(m.CatalogImport).where(*condition))
        await self._commit()
