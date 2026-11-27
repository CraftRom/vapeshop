from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class CatalogMixin:
    @staticmethod
    def _category_scope(category_id):
        children = select(m.Subcategory.id).where(m.Subcategory.category_id == category_id).correlate(m.Category)
        return or_(m.Product.category_id == category_id, m.Product.subcategory_id.in_(children))

    @staticmethod
    def _filters(query, category_id=None, subcategory_id=None, search=None,
                 only_active=False, is_new=None, is_sale=None, uncategorized=False,inventory=None):
        if inventory:
            sellable=and_(_published(),m.Product.price>0,func.trim(m.Product.name)!='')
            conditions={
                'available':and_(sellable,m.Product.stock>0),
                'low':and_(sellable,m.Product.stock>0,m.Product.stock<=3),
                'out':and_(sellable,m.Product.stock<=0),
                'unpriced':and_(_published(),m.Product.price<=0),
                # Hidden on the storefront: individually or through a hidden group.
                'hidden':not_(_published()),
                'missing_photos':and_(sellable,func.trim(func.coalesce(m.Product.photo_url,''))=='',func.trim(func.coalesce(m.Product.photo_file_id,''))=='')}
            query=query.where(conditions[inventory])
        if category_id is not None:
            query = query.where(CatalogMixin._category_scope(category_id))
        if subcategory_id is not None:
            query = query.where(m.Product.subcategory_id == subcategory_id)
        if uncategorized:
            query = query.where(m.Product.category_id.is_(None), m.Product.subcategory_id.is_(None))
        if search:
            query = query.where(or_(m.Product.name_lower.contains(search.lower(), autoescape=True),
                                   m.Product.sku.icontains(search, autoescape=True),
                                   m.Product.external_sku.icontains(search, autoescape=True)))
        if only_active:
            query = query.where(_published())
        if is_new is not None:
            query = query.where(m.Product.is_new.is_(is_new))
        if is_sale is not None:
            query = query.where(m.Product.is_sale.is_(is_sale))
        return query

    async def list_categories(self, only_active=False) -> list[Category]:
        count = select(func.count(m.Product.id)).where(self._category_scope(m.Category.id))
        if only_active:
            count = count.where(m.Product.is_active.is_(True))
        query = select(m.Category, count.correlate(m.Category).scalar_subquery()).order_by(m.Category.sort_order, m.Category.name)
        if only_active:
            query = query.where(m.Category.is_active.is_(True))
        return [_category(row, cnt) for row, cnt in await self.s.execute(query)]

    async def get_category(self, category_id):
        row = await self.s.get(m.Category, category_id)
        return _category(row) if row else None

    async def create_category(self, data):
        row = m.Category(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _category(row)

    async def update_category(self, category_id, data):
        row = await self.s.get(m.Category, category_id)
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        return _category(row)

    async def delete_category(self, category_id):
        result = await self.s.execute(update(m.Product).where(self._category_scope(category_id), m.Product.is_active.is_(True)).values(is_active=False))
        await self.s.execute(update(m.Category).where(m.Category.id == category_id).values(is_active=False))
        await self.s.execute(update(m.Subcategory).where(m.Subcategory.category_id == category_id).values(is_active=False))
        await self._commit()
        return int(result.rowcount or 0)

    async def list_subcategories(self, category_id=None, only_active=False):
        counts = select(m.Product.subcategory_id, func.count(m.Product.id).label("cnt"))
        if only_active:
            counts = counts.where(m.Product.is_active.is_(True))
        counts = counts.group_by(m.Product.subcategory_id).subquery()
        query = (select(m.Subcategory, m.Category.name, func.coalesce(counts.c.cnt, 0))
                 .outerjoin(m.Category, m.Category.id == m.Subcategory.category_id)
                 .outerjoin(counts, counts.c.subcategory_id == m.Subcategory.id)
                 .order_by(m.Subcategory.sort_order, m.Subcategory.name))
        if category_id is not None:
            query = query.where(m.Subcategory.category_id == category_id)
        if only_active:
            query = query.where(m.Subcategory.is_active.is_(True), or_(m.Subcategory.category_id.is_(None), m.Category.is_active.is_(True)))
        return [Subcategory(**vars(_category(row, cnt)), category_id=row.category_id, category_name=name)
                for row, name, cnt in await self.s.execute(query)]

    async def get_subcategory(self, subcategory_id):
        result = await self.s.execute(select(m.Subcategory, m.Category.name).outerjoin(m.Category, m.Category.id == m.Subcategory.category_id).where(m.Subcategory.id == subcategory_id))
        pair = result.first()
        if not pair:
            return None
        row, name = pair
        return Subcategory(**vars(_category(row)), category_id=row.category_id, category_name=name)

    async def create_subcategory(self, data):
        await self._validate_group(data)
        row = m.Subcategory(**data)
        self.s.add(row)
        await self.s.commit()
        return await self.get_subcategory(row.id)

    async def update_subcategory(self, subcategory_id, data):
        row = await self.s.get(m.Subcategory, subcategory_id)
        if not row:
            return None
        await self._validate_group(data)
        parent = data.get("category_id", row.category_id)
        # Moving a group must move explicit parent assignments with it.
        if parent != row.category_id:
            await self.s.execute(update(m.Product).where(m.Product.subcategory_id == subcategory_id, m.Product.category_id.is_not(None)).values(category_id=parent))
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        return await self.get_subcategory(row.id)

    async def delete_subcategory(self, subcategory_id):
        result = await self.s.execute(update(m.Product).where(m.Product.subcategory_id == subcategory_id, m.Product.is_active.is_(True)).values(is_active=False))
        await self.s.execute(update(m.Subcategory).where(m.Subcategory.id == subcategory_id).values(is_active=False))
        await self._commit()
        return int(result.rowcount or 0)

    async def purge_subcategory(self, subcategory_id):
        ids = list(await self.s.scalars(select(m.Product.id).where(m.Product.subcategory_id == subcategory_id)))
        for product_id in ids:
            await self.purge_product(product_id)
        await self.s.execute(delete(m.Subcategory).where(m.Subcategory.id == subcategory_id))
        await self._commit()
        return len(ids)

    async def list_products(self, category_id=None, search=None, only_active=False, limit=500, offset=0,
                            subcategory_id=None, is_new=None, is_sale=None, uncategorized=False,
                            inventory=None,sort=None):
        query = (select(m.Product, m.Category.name, m.Subcategory.name, _parents_active())
                 .outerjoin(m.Category, m.Category.id == m.Product.category_id)
                 .outerjoin(m.Subcategory, m.Subcategory.id == m.Product.subcategory_id))
        query = self._filters(query, category_id, subcategory_id, search, only_active, is_new, is_sale, uncategorized,inventory)
        ordering={'name-asc':m.Product.name.asc(),'name-desc':m.Product.name.desc(),
            'price-asc':m.Product.price.asc(),'price-desc':m.Product.price.desc(),
            'stock-asc':m.Product.stock.asc(),'stock-desc':m.Product.stock.desc()}
        columns=[ordering[sort],m.Product.id] if sort else [m.Product.sort_order,m.Product.name,m.Product.id]
        query=query.order_by(*columns).limit(limit).offset(offset)
        return [_product(row, name, subname, active) for row, name, subname, active in await self.s.execute(query.execution_options(populate_existing=True))]

    async def products_by_ids(self, ids):
        if not ids:
            return []
        query = (select(m.Product, m.Category.name, m.Subcategory.name, _parents_active())
                 .outerjoin(m.Category, m.Category.id == m.Product.category_id)
                 .outerjoin(m.Subcategory, m.Subcategory.id == m.Product.subcategory_id)
                 .where(m.Product.id.in_(list(ids))))
        return [_product(row, name, subname, active) for row, name, subname, active in await self.s.execute(query.execution_options(populate_existing=True))]

    async def count_products(self, category_id=None, only_active=True, **filters):
        query = self._filters(select(func.count(m.Product.id)), category_id=category_id, only_active=only_active, **filters)
        return await self.s.scalar(query) or 0

    async def get_product(self, product_id):
        rows = await self.products_by_ids([product_id])
        return rows[0] if rows else None

    async def _validate_group(self, data):
        cid, sid = data.get("category_id"), data.get("subcategory_id")
        if cid is not None and not await self.s.get(m.Category, cid):
            raise ValueError("Такої категорії немає")
        if sid is not None:
            sub = await self.s.get(m.Subcategory, sid)
            if not sub:
                raise ValueError("Такої субкатегорії немає")
            if cid is not None and sub.category_id is not None and sub.category_id != cid:
                raise ValueError("Субкатегорія належить іншій категорії")

    async def _validate_product(self, data):
        await self._validate_group(data)
        if data.get("is_sale") and (data.get("old_price") is None or Decimal(str(data["old_price"])) <= Decimal(str(data["price"]))):
            raise ValueError("Для акції стара ціна має бути більшою за поточну")
        for key in ("price", "old_price", "stock"):
            if data.get(key) is not None and Decimal(str(data[key])) < 0:
                raise ValueError("Ціна й залишок не можуть бути від’ємними")

    async def create_product(self, data):
        from shop.services.product_io import generate_sku
        data = dict(data)
        supplied = data.pop("sku", None)
        if supplied and not data.get("external_sku"):
            data["external_sku"] = str(supplied)[:255]
        data.setdefault("is_sale", bool(data.get("old_price") is not None and data["old_price"] > data["price"]))
        await self._validate_product(data)
        group = await self.get_subcategory(data["subcategory_id"]) if data.get("subcategory_id") else await self.get_category(data["category_id"]) if data.get("category_id") else None
        data["name_lower"] = data["name"].lower()
        for attempt in range(5):
            data["sku"] = await generate_sku(self, group.name if group else "GEN")
            row = m.Product(**data)
            self.s.add(row)
            try:
                await self.s.commit()
                return await self.get_product(row.id)
            except IntegrityError as exc:
                await self.s.rollback()
                if "sku" not in str(exc).lower() or attempt == 4:
                    raise
        raise RuntimeError("Не вдалося створити товар")

    async def get_product_by_sku(self, sku):
        row = await self.s.scalar(select(m.Product).where(m.Product.sku == sku.strip().upper()))
        return await self.get_product(row.id) if row else None

    async def get_product_by_external_sku(self, sku):
        rows = list(await self.s.scalars(select(m.Product.id).where(func.trim(m.Product.external_sku) == sku.strip()).limit(2)))
        if len(rows) > 1:
            raise ValueError("Зовнішній артикул неоднозначний — використайте системний SKU")
        return await self.get_product(rows[0]) if rows else None

    async def update_product(self, product_id, data):
        row = await self.s.get(m.Product, product_id)
        if not row:
            return None
        data = dict(data)
        data.pop("sku", None)  # The system article is immutable.
        merged = {key: getattr(row, key) for key in ("category_id", "subcategory_id", "price", "old_price", "stock", "is_sale")}
        merged.update(data)
        await self._validate_product(merged)
        for key, value in data.items():
            setattr(row, key, value)
        if "name" in data:
            row.name_lower = data["name"].lower()
        await self.s.commit()
        return await self.get_product(product_id)

    async def adjust_stock(self, product_id, delta: int) -> Product | None:
        # Відʼємний зсув — це резерв товару, а не просто «не піти в мінус».
        # Старий CASE(stock + delta, 0) дозволяв двом одночасним checkout
        # обом пройти перевірку залишку: другий теж створював замовлення,
        # а склад просто затискався в нуль. Тепер UPDATE виконується лише
        # якщо потрібна кількість реально ще є.
        query = update(m.Product).where(m.Product.id == product_id)
        if delta < 0:
            query = query.where(m.Product.stock >= -delta)
        result = await self.s.execute(query.values(stock=_not_below_zero(m.Product.stock + delta)))
        await self._commit()
        if not result.rowcount:
            return None
        return await self.get_product(product_id)

    async def set_stock(self, product_id, stock: int) -> Product | None:
        row = await self.s.get(m.Product, product_id)
        if not row:
            return None
        row.stock = max(0, stock)
        await self.s.commit()
        return await self.get_product(product_id)

    async def count_low_stock(self, threshold=5) -> int:
        return await self.s.scalar(
            select(func.count(m.Product.id))
            .where(m.Product.is_active.is_(True), m.Product.stock < threshold)
        ) or 0
