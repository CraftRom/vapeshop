from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class OrdersMixin:
    async def create_order(self, order: Order, lines: list[OrderLine]) -> Order:
        row = m.Order(
            user_id=order.user_id, subtotal=order.subtotal, discount=order.discount,
            bonus_used=order.bonus_used, total=order.total,
            promo_code_id=order.promo_code_id, payment_method=order.payment_method,
            attribution=order.attribution, checkout_key=order.checkout_key, crm_state=order.crm_state,
            contact_name=order.contact_name, contact_surname=order.contact_surname,
            contact_patronymic=order.contact_patronymic, contact_phone=order.contact_phone,
            delivery_city=order.delivery_city, delivery_address=order.delivery_address,
            delivery_method=order.delivery_method,
            delivery_city_ref=order.delivery_city_ref,
            delivery_warehouse_ref=order.delivery_warehouse_ref,
            comment=order.comment,
            search_key=f"{order.contact_name or ''} {order.contact_phone or ''}".lower(),
        )
        self.s.add(row)
        try:
            await self.s.flush()
            for line in lines:
                self.s.add(m.OrderItem(
                    order_id=row.id, product_id=line.product_id,
                    name=line.name, price=line.price, qty=line.qty,
                ))
            await self.s.commit()
        except Exception:
            # Після IntegrityError (найчастіше одночасний повтор того самого
            # checkout_key) SQLAlchemy блокує сесію до rollback. Без цього
            # сервіс не міг ані повернути резерв складу, ані прочитати вже
            # створене першим запитом замовлення.
            await self.s.rollback()
            raise
        loaded = await self.s.scalar(
            select(m.Order).where(m.Order.id == row.id).options(selectinload(m.Order.items))
        )
        created = _order(loaded)
        _emit_order_changed(created, ("status", "business_state", "crm_state"), created=True)
        return created

    async def create_checkout_order_atomic(
        self, order: Order, lines: list[OrderLine], *, promo_id: int | None = None,
        bonus_used=Decimal(0),
    ):
        """Створює checkout одним SQL-транзакційним комітом.

        Раніше reserve stock, insert order, promo usage, bonus spend і clear
        cart комітились окремо. Падіння процесу між ними залишало або
        «зниклий» товар без замовлення, або замовлення без списаних бонусів.
        Тут усі критичні зміни або проходять разом, або rollback-яться разом.

        Повертає ``(order, status)`` де status: created / duplicate / stock /
        promo / bonus.
        """
        bonus_used = Decimal(str(bonus_used or 0))
        try:
            # Один user-lock серіалізує checkout із cart +/- і з другим
            # checkout того самого покупця. Після lock ще раз звіряємо кошик:
            # snapshot, який сервіс порахував до транзакції, не можна мовчки
            # оформити, якщо інша вкладка встигла його змінити.
            user_row = await self.s.scalar(
                select(m.User).where(m.User.id == order.user_id).with_for_update()
            )
            if not user_row:
                await self.s.rollback()
                return None, "cart"

            # Після очікування user-lock перший конкурентний checkout уже
            # міг завершитися й очистити кошик. У такому випадку спершу
            # перевіряємо idempotency key, інакше другий той самий POST
            # помилково отримав би «кошик змінився» замість існуючого order.
            if order.checkout_key:
                existing_row = await self.s.scalar(
                    select(m.Order).where(m.Order.checkout_key == order.checkout_key)
                    .options(selectinload(m.Order.items), selectinload(m.Order.user))
                )
                if existing_row:
                    existing = _order(existing_row, with_user=True)
                    await self.s.rollback()
                    if existing.user_id == order.user_id:
                        return existing, "duplicate"
                    # Чужий ключ не розкриваємо через доменний checkout path.
                    return None, "duplicate_conflict"

            current_cart_rows = list((await self.s.execute(
                select(m.CartItem.product_id, m.CartItem.qty)
                .where(m.CartItem.user_id == order.user_id)
                .order_by(m.CartItem.product_id)
            )).all())
            expected_cart = sorted((int(line.product_id), int(line.qty)) for line in lines)
            current_cart = sorted((int(product_id), int(qty)) for product_id, qty in current_cart_rows)
            if current_cart != expected_cart:
                await self.s.rollback()
                return None, "cart"

            # Серіалізуємо перевірку промокоду: загальний max_uses і
            # per-user limit не можуть бути перевищені двома checkout одночасно.
            if promo_id:
                promo = await self.s.scalar(
                    select(m.PromoCode).where(m.PromoCode.id == promo_id).with_for_update()
                    .execution_options(populate_existing=True)
                )
                if not promo or not promo.is_active:
                    await self.s.rollback()
                    return None, "promo"
                now = datetime.now(timezone.utc)
                expires = promo.expires_at
                if expires and expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires and expires < now:
                    await self.s.rollback()
                    return None, "promo"
                if promo.max_uses is not None and promo.used_count >= promo.max_uses:
                    await self.s.rollback()
                    return None, "promo"
                if Decimal(str(order.subtotal or 0)) < Decimal(str(promo.min_order or 0)):
                    await self.s.rollback()
                    return None, "promo"
                used_by_user = await self.s.scalar(
                    select(func.count(m.PromoUsage.id)).where(
                        m.PromoUsage.promo_id == promo_id,
                        m.PromoUsage.user_id == order.user_id,
                    )
                ) or 0
                if used_by_user >= promo.per_user_limit:
                    await self.s.rollback()
                    return None, "promo"

            # Баланс перевіряємо під тим самим user-lock: два checkout
            # не можуть витратити ті самі бонуси.
            if bonus_used > 0:
                if Decimal(str(user_row.bonus_balance or 0)) < bonus_used:
                    await self.s.rollback()
                    return None, "bonus"

            # Товари блокуємо у стабільному порядку ID: два checkout із
            # однаковими товарами, доданими в різному порядку, інакше могли
            # отримати взаємний deadlock. Під lock повторно звіряємо active,
            # stock і ціну — validate_cart() був лише попереднім snapshot.
            locked_lines = []
            for line in sorted(lines, key=lambda item: int(item.product_id)):
                product = await self.s.scalar(
                    select(m.Product).where(m.Product.id == line.product_id).with_for_update()
                    .execution_options(populate_existing=True)
                )
                if not await self._row_published(product) or int(product.stock or 0) < int(line.qty):
                    await self.s.rollback()
                    return None, "stock"
                if Decimal(str(product.price)) != Decimal(str(line.price)):
                    await self.s.rollback()
                    return None, "cart"
                locked_lines.append(CartLine(product_id=product.id, qty=line.qty, product=product))
                product.stock = int(product.stock or 0) - int(line.qty)

            if promo_id:
                # Recheck scope against the current, locked products as well as
                # the locked promo. A category change must not reuse an old quote.
                sub_ids = {line.product.subcategory_id for line in locked_lines
                           if line.product.subcategory_id is not None}
                parents = {}
                if promo.category_ids and sub_ids:
                    parents = {s.id: s.category_id for s in await self.s.scalars(
                        select(m.Subcategory).where(m.Subcategory.id.in_(sub_ids))
                        .order_by(m.Subcategory.id).with_for_update()
                        .execution_options(populate_existing=True)
                    )}
                base = eligible_subtotal(locked_lines, promo.category_ids, parents)
                if base <= 0 or promo_discount(promo, base) != Decimal(str(order.discount or 0)):
                    await self.s.rollback()
                    return None, "promo"

            row = m.Order(
                user_id=order.user_id, subtotal=order.subtotal, discount=order.discount,
                bonus_used=order.bonus_used, total=order.total,
                promo_code_id=order.promo_code_id, payment_method=order.payment_method,
                attribution=order.attribution, checkout_key=order.checkout_key, crm_state=order.crm_state,
                contact_name=order.contact_name, contact_surname=order.contact_surname,
                contact_patronymic=order.contact_patronymic, contact_phone=order.contact_phone,
                delivery_city=order.delivery_city, delivery_address=order.delivery_address,
                delivery_method=order.delivery_method, delivery_city_ref=order.delivery_city_ref,
                delivery_warehouse_ref=order.delivery_warehouse_ref, comment=order.comment,
                search_key=f"{order.contact_name or ''} {order.contact_phone or ''}".lower(),
            )
            self.s.add(row)
            await self.s.flush()
            for line in lines:
                self.s.add(m.OrderItem(
                    order_id=row.id, product_id=line.product_id, name=line.name,
                    price=line.price, qty=line.qty,
                ))

            if promo_id:
                self.s.add(m.PromoUsage(
                    promo_id=promo_id, user_id=order.user_id, order_id=row.id,
                ))
                promo.used_count += 1

            if bonus_used > 0:
                self.s.add(m.BonusTx(
                    user_id=order.user_id, amount=-bonus_used, reason="spend", order_id=row.id,
                ))
                user_row.bonus_balance = Decimal(str(user_row.bonus_balance or 0)) - bonus_used

            await self.s.execute(delete(m.CartItem).where(m.CartItem.user_id == order.user_id))
            await self.s.commit()
        except IntegrityError:
            # Найімовірніше — конкурентний insert того самого checkout_key.
            # Rollback повертає і резерв складу, і promo/bonus зміни.
            await self.s.rollback()
            if order.checkout_key:
                existing = await self.get_order_by_checkout_key(order.checkout_key)
                if existing and existing.user_id == order.user_id:
                    return existing, "duplicate"
            raise
        except Exception:
            await self.s.rollback()
            raise

        loaded = await self.s.scalar(
            select(m.Order).where(m.Order.id == row.id)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        created = _order(loaded, with_user=True)
        _emit_order_changed(created, ("status", "business_state", "crm_state"), created=True)
        return created, "created"

    async def get_order(self, order_id) -> Order | None:
        row = await self.s.scalar(
            select(m.Order).where(m.Order.id == order_id)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        return _order(row, with_user=True)

    async def get_order_by_checkout_key(self, checkout_key: str) -> Order | None:
        key = str(checkout_key or "").strip()
        if not key:
            return None
        row = await self.s.scalar(
            select(m.Order).where(m.Order.checkout_key == key)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        return _order(row, with_user=True)

    async def _order_filters(self, query, status=None, search=None, user_id=None,
                             date_from=None, date_to=None, crm_status_id=None,
                             legacy_only=False, active_only=False, channel=None, queue=None,
                             payment_method=None, delivery_method=None):
        from shop.services.commerce_workspace import channel_expression,queue_condition
        if channel:query=query.where(channel_expression()==channel)
        if queue:query=query.where(queue_condition(queue))
        for column,value in [(m.Order.payment_method,payment_method),(m.Order.delivery_method,delivery_method)]:
            if value=='unknown':query=query.where(or_(column.is_(None),func.trim(column)==''))
            elif value:query=query.where(column==value)
        if status:
            query = query.where(m.Order.status == status)
        if crm_status_id is not None:
            query = query.where(m.Order.crm_id.is_not(None), m.Order.crm_status_id == str(crm_status_id))
        if legacy_only:
            query = query.where(m.Order.crm_id.is_(None))
        if user_id is not None:
            query = query.where(m.Order.user_id == user_id)
        if active_only:
            from shop.services.order_chat import OPEN_STATUSES
            query = query.where(m.Order.status.in_(OPEN_STATUSES))
        if search:
            term=search.strip()
            matches=[m.Order.search_key.contains(term.casefold(),autoescape=True),m.Order.tracking_number.contains(term,autoescape=True)]
            digits=''.join(char for char in term if char in '0123456789')
            if len(digits)>=7:matches.append(m.Order.contact_phone.contains(digits,autoescape=True))
            number=term.removeprefix('#')
            if number.isascii() and number.isdigit() and 0<int(number)<=2**31-1:matches.append(m.Order.id==int(number))
            query=query.where(or_(*matches))
        if date_from or date_to:
            from shop.services.calendar import day_bounds, validate_dates
            from shop.services.shop_settings import get_shop_settings
            validate_dates(date_from, date_to)
            tz = (await get_shop_settings(self)).tz
            if date_from:
                query = query.where(m.Order.created_at >= day_bounds(date_from, tz)[0])
            if date_to:
                query = query.where(m.Order.created_at < day_bounds(date_to, tz)[1])
        return query

    async def list_orders(self, status=None, search=None, user_id=None,
                          date_from=None, date_to=None, limit=100, offset=0,
                          crm_status_id=None, legacy_only=False, active_only=False,
                          channel=None, queue=None,payment_method=None,delivery_method=None):
        query = await self._order_filters(
            select(m.Order), status, search, user_id, date_from, date_to,
            crm_status_id, legacy_only, active_only,channel,queue,payment_method,delivery_method)
        query = query.options(selectinload(m.Order.items), selectinload(m.Order.user))
        query = query.order_by(m.Order.created_at.desc(), m.Order.id.desc()).limit(limit).offset(offset)
        return [_order(r, with_user=True) for r in await self.s.scalars(query)]

    async def count_filtered_orders(self, **filters):
        query = await self._order_filters(select(func.count()).select_from(m.Order), **filters)
        return int(await self.s.scalar(query) or 0)

    async def list_crm_refresh_candidates(
        self, *, stale_before: datetime,
        terminal_stale_before: datetime | None = None,
        limit: int = 20,
    ):
        """Невелика справедлива порція заявок для фонового SalesDrive pull.

        Pending бізнес-результати перевіряємо першими: саме серед них може
        ховатися новий statusCode 9/102/103. Усередині групи беремо найстаріший
        snapshot, щоб при великій базі жодне замовлення не голодувало.
        """
        terminal_cutoff = terminal_stale_before or stale_before
        pending_state = or_(
            m.Order.business_state.is_(None),
            m.Order.business_state == business.BUSINESS_PENDING,
        )
        terminal_state = and_(
            m.Order.business_state.is_not(None),
            m.Order.business_state != business.BUSINESS_PENDING,
        )
        query = (
            select(m.Order)
            .where(
                m.Order.crm_id.is_not(None),
                or_(
                    m.Order.crm_fetched_at.is_(None),
                    and_(pending_state, m.Order.crm_fetched_at < stale_before),
                    and_(terminal_state, m.Order.crm_fetched_at < terminal_cutoff),
                ),
            )
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
            .order_by(
                case((m.Order.business_state == business.BUSINESS_PENDING, 0), else_=1),
                m.Order.crm_fetched_at.asc().nullsfirst(),
                m.Order.id.asc(),
            )
            .limit(max(1, int(limit)))
        )
        return [_order(r, with_user=True) for r in await self.s.scalars(query)]

    async def update_order(self, order_id, data: dict) -> Order | None:
        """Оновлює замовлення й комерційний state однією транзакцією.

        ``business_state`` не можна ставити звичайним setattr: разом із ним
        мусять синхронно змінитися customer totals. Тому як CRM transition,
        так і legacy transition проходять через ``_apply_business_state_row``.
        """
        row = await self.s.scalar(
            select(m.Order).where(m.Order.id == order_id).with_for_update()
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        if not row:
            return None

        was_closed = is_closed(row)
        previous_crm_status_id = str(row.crm_status_id or "")
        requested_business_state = data.get("business_state") if "business_state" in data else None
        requested_business_at = data.get("business_state_at") if "business_state_at" in data else None
        for key, value in data.items():
            if key in {"business_state", "business_state_at"}:
                continue
            setattr(row, key, value)

        next_state = requested_business_state
        if "crm_status_name" in data:
            # CRM має пріоритет над будь-яким local-derived значенням.
            next_state = business.state_from_crm_status_name(data.get("crm_status_name"))
            incoming_id = str(data.get("crm_status_id") or row.crm_status_id or "")
            if next_state is None and "crm_status_id" in data and incoming_id != previous_crm_status_id:
                next_state = business.BUSINESS_PENDING

        if next_state is not None:
            moment = requested_business_at or datetime.now(timezone.utc)
            await self._apply_business_state_row(row, next_state, moment)

        record_completion(row, was_closed, requested_business_at)
        await self.s.commit()
        updated = _order(row, with_user=True)
        changed_fields = set(str(k) for k in data.keys())
        if "crm_status_name" in data or "business_state" in data:
            changed_fields.add("business_state")
        _emit_order_changed(updated, changed_fields)
        return updated

    async def transition_order_status_atomic(
        self, order_id: int, expected_status: OrderStatus, target_status: OrderStatus,
        patch: dict | None = None,
    ):
        """Compare-and-set local workflow status under a row lock.

        All status writers (panel, bot, SalesDrive progression) can race.
        Checking the expected value in the same transaction prevents a stale
        request from moving the order backwards after a newer writer committed.
        """
        patch = dict(patch or {})
        try:
            row = await self.s.scalar(
                select(m.Order).where(m.Order.id == order_id).with_for_update()
                .options(selectinload(m.Order.items), selectinload(m.Order.user))
            )
            if not row:
                await self.s.rollback()
                return None, expected_status, False

            current = OrderStatus(row.status.value)
            if current != expected_status:
                fresh = _order(row, with_user=True)
                await self.s.rollback()
                return fresh, current, False
            if current == target_status:
                fresh = _order(row, with_user=True)
                await self.s.rollback()
                return fresh, current, False

            was_closed = is_closed(row)
            previous_crm_status_id = str(row.crm_status_id or "")
            requested_business_state = patch.get("business_state") if "business_state" in patch else None
            requested_business_at = patch.get("business_state_at") if "business_state_at" in patch else None
            row.status = m.OrderStatus(target_status.value)
            for key, value in patch.items():
                if key in {"status", "business_state", "business_state_at"}:
                    continue
                setattr(row, key, value)

            next_state = requested_business_state
            if "crm_status_name" in patch:
                next_state = business.state_from_crm_status_name(patch.get("crm_status_name"))
                incoming_id = str(patch.get("crm_status_id") or row.crm_status_id or "")
                if next_state is None and "crm_status_id" in patch and incoming_id != previous_crm_status_id:
                    next_state = business.BUSINESS_PENDING
            if next_state is not None:
                await self._apply_business_state_row(
                    row, next_state, requested_business_at or datetime.now(timezone.utc)
                )

            record_completion(row, was_closed, requested_business_at)
            await self.s.commit()
            loaded = await self.s.scalar(
                select(m.Order).where(m.Order.id == order_id)
                .options(selectinload(m.Order.items), selectinload(m.Order.user))
            )
            fresh = _order(loaded, with_user=True)
            fields = set(str(k) for k in patch.keys()) | {"status"}
            if "crm_status_name" in patch or "business_state" in patch:
                fields.add("business_state")
            _emit_order_changed(fresh, fields)
            return fresh, current, True
        except Exception:
            await self.s.rollback()
            raise

    async def cancel_order_atomic(
        self, order_id: int, expected_status: OrderStatus, *, mark_crm_pending: bool = False,
    ):
        """Скасовує замовлення й повертає склад/бонуси одним COMMIT.

        Order row-lock робить операцію exactly-once для БД: два одночасні
        cancel не можуть двічі повернути той самий товар або бонуси.
        ``expected_status`` захищає від stale UI — якщо інший процес уже
        пересунув замовлення, цей запит нічого не відкотить.
        """
        try:
            row = await self.s.scalar(
                select(m.Order).where(m.Order.id == order_id).with_for_update()
                .options(selectinload(m.Order.items), selectinload(m.Order.user))
            )
            if not row:
                await self.s.rollback()
                return None, expected_status, False

            current = OrderStatus(row.status.value)
            if current != expected_status:
                fresh = _order(row, with_user=True)
                await self.s.rollback()
                return fresh, current, False
            if current == OrderStatus.CANCELLED:
                fresh = _order(row, with_user=True)
                await self.s.rollback()
                return fresh, current, False

            # Lock-order узгоджений із checkout/cart: спочатку User, потім
            # Product. Якби cancellation тримав Product і лише потім чекав
            # User, паралельний cart (User → Product) утворював би deadlock.
            user_row = await self.s.scalar(
                select(m.User).where(m.User.id == row.user_id).with_for_update()
            )

            # Products у стабільному порядку: скасування двох різних
            # замовлень із перетином товарів не створює lock inversion.
            for item in sorted(row.items, key=lambda x: int(x.product_id or 0)):
                if not item.product_id:
                    continue
                product = await self.s.scalar(
                    select(m.Product).where(m.Product.id == item.product_id).with_for_update()
                )
                if product:
                    product.stock = int(product.stock or 0) + int(item.qty or 0)

            crm_linked = business.has_crm_authority(row)
            if user_row:
                # Для CRM-пов'язаних замовлень комерційний результат змінює
                # тільки авторитетний CRM-статус. Local cancel не має сам
                # прибирати вже зафіксований продаж до підтвердження CRM.
                if not crm_linked and str(row.business_state or "pending") == "sale":
                    user_row.orders_count = max(0, int(user_row.orders_count or 0) - 1)
                    user_row.total_spent = max(
                        Decimal(0), Decimal(str(user_row.total_spent or 0)) - Decimal(str(row.total or 0))
                    )
                bonus = Decimal(str(row.bonus_used or 0))
                if bonus > 0:
                    self.s.add(m.BonusTx(
                        user_id=row.user_id, amount=bonus, reason="refund", order_id=row.id,
                    ))
                    user_row.bonus_balance = Decimal(str(user_row.bonus_balance or 0)) + bonus

            was_closed = is_closed(row)
            row.status = m.OrderStatus.CANCELLED
            if not crm_linked:
                row.business_state = "refusal"
                row.business_state_at = datetime.now(timezone.utc)
            if mark_crm_pending and (row.crm_id or row.crm_state):
                row.crm_state = "pending"
            record_completion(row, was_closed)
            await self.s.commit()
            loaded = await self.s.scalar(
                select(m.Order).where(m.Order.id == order_id)
                .options(selectinload(m.Order.items), selectinload(m.Order.user))
            )
            fresh = _order(loaded, with_user=True)
            _emit_order_changed(
                fresh, ("status", "crm_state", "business_state", "stock", "bonus_balance")
            )
            return fresh, current, True
        except Exception:
            await self.s.rollback()
            raise

    async def find_order_by_crm_id(self, crm_id: str) -> Order | None:
        row = await self.s.scalar(
            select(m.Order).where(m.Order.crm_id == str(crm_id))
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        return _order(row, with_user=True)

    async def orders_for_crm_sync(self, states, limit: int = 50) -> list[Order]:
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import and_, or_
        states = list(states)
        # «creating» свіжий — означає, що відправка саме йде в процесі API.
        # Узяти його зараз означало б створити дубль заявки. Старший за
        # десять хвилин — процес упав посеред запиту, і стан невідомий.
        stale = datetime.now(timezone.utc) - timedelta(minutes=10)
        plain = [s for s in states if s != "creating"]
        condition = m.Order.crm_state.in_(plain)
        if "creating" in states:
            condition = or_(condition, and_(m.Order.crm_state == "creating",
                                            m.Order.updated_at < stale))
        rows = await self.s.scalars(
            select(m.Order).where(condition)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
            .order_by(m.Order.id).limit(limit)
        )
        return [_order(r, with_user=True) for r in rows]

    async def count_orders(self, status=None) -> int:
        query = select(func.count(m.Order.id))
        if status:
            query = query.where(m.Order.status == status)
        return await self.s.scalar(query) or 0

    async def count_display_new_orders(self, crm_new_status_id: str | None = None) -> int:
        """Єдиний глобальний лічильник «Нових» для legacy + SalesDrive.

        Для CRM-linked заявок локальний workflow більше не авторитетний.
        Виняток — коротке вікно одразу після створення, коли crm_id вже є,
        але snapshot/statusId ще не повернувся: таке замовлення справді нове.
        """
        legacy_new = and_(
            m.Order.crm_id.is_(None),
            m.Order.status == OrderStatus.NEW,
        )
        unresolved_crm_new = and_(
            m.Order.crm_id.is_not(None),
            or_(m.Order.crm_status_id.is_(None), m.Order.crm_status_id == ""),
            m.Order.status == OrderStatus.NEW,
        )

        crm_new_id = str(crm_new_status_id or "").strip()
        if crm_new_id:
            crm_new = and_(
                m.Order.crm_id.is_not(None),
                m.Order.crm_status_id == crm_new_id,
            )
        else:
            # Compatibility fallback для ще не налаштованої status map.
            crm_new = and_(
                m.Order.crm_id.is_not(None),
                func.lower(func.trim(m.Order.crm_status_name)).in_(("новий", "нове", "new")),
            )

        query = select(func.count(m.Order.id)).where(
            or_(legacy_new, unresolved_crm_new, crm_new)
        )
        return int(await self.s.scalar(query) or 0)

    async def status_breakdown(self) -> dict[str, int]:
        rows = await self.s.execute(
            select(m.Order.status, func.count(m.Order.id)).group_by(m.Order.status)
        )
        return {status.value: count for status, count in rows}

    async def display_status_breakdown(
        self, *, since: datetime | None = None, until: datetime | None = None,
    ) -> list[dict]:
        """Групування для панелі без змішування local status із SalesDrive.

        Якщо передані межі, розріз відповідає тому самому періоду, що й решта
        сторінки статистики. Раніше статуси завжди були «за весь час», навіть
        коли зверху обирали «Сьогодні» — числа в одному екрані суперечили одне
        одному.
        """
        crm_query = (
            select(m.Order.crm_status_id, func.max(m.Order.crm_status_name), func.count(m.Order.id))
            .where(m.Order.crm_id.is_not(None))
        )
        legacy_query = (
            select(m.Order.status, func.count(m.Order.id))
            .where(m.Order.crm_id.is_(None))
        )
        if since is not None:
            crm_query = crm_query.where(m.Order.created_at >= since)
            legacy_query = legacy_query.where(m.Order.created_at >= since)
        if until is not None:
            crm_query = crm_query.where(m.Order.created_at < until)
            legacy_query = legacy_query.where(m.Order.created_at < until)
        crm_rows = await self.s.execute(crm_query.group_by(m.Order.crm_status_id))
        legacy_rows = await self.s.execute(legacy_query.group_by(m.Order.status))
        result = [
            {
                "source": "crm",
                "status": str(status_id or ""),
                "name": str(status_name or "").strip(),
                "count": int(count),
            }
            for status_id, status_name, count in crm_rows
        ]
        result.extend(
            {"source": "legacy", "status": status.value, "name": "", "count": int(count)}
            for status, count in legacy_rows
        )
        return result
