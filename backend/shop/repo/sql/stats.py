from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403


class StatsMixin:
    async def stats_summary(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None,
    ) -> Stats:
        """Фінанси за фактичними продажами, а не за local workflow.

        У період продаж потрапляє за ``business_state_at`` — моментом, коли
        авторитетний CRM-статус став «Продаж». Це виправляє стару помилку,
        коли замовлення, створене в одному місяці й продане в іншому,
        приписувалось місяцю створення.
        """
        now = datetime.now(timezone.utc)
        period_since = since or (
            now - timedelta(days=days) if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        period_until = until or now

        sale_rows = list((await self.s.execute(
            select(
                m.Order.status, m.Order.business_state, m.Order.business_state_at,
                m.Order.payment_method, m.Order.total, m.Order.crm_snapshot,
                m.Order.created_at, m.Order.user_id,
            ).where(m.Order.business_state == business.BUSINESS_SALE)
        )).all())

        sales_total = received_total = expected_total = Decimal(0)
        actual_total = calculated_total = Decimal(0)
        sales_period = received_period = expected_period = Decimal(0)
        actual_period = calculated_period = Decimal(0)
        sales_count = sales_period_count = 0
        received_period_count = 0
        buyers_period: set[int] = set()

        for row in sale_rows:
            fin = stats_finance_values(
                row.business_state, row.status,
                _stats_payment_method(row, row.crm_snapshot or {}),
                row.total, row.crm_snapshot,
            )
            sales_total += fin["total"]
            received_total += fin["received"]
            expected_total += fin["expected"]
            actual_total += fin["actual_received"]
            calculated_total += fin["calculated_received"]
            sales_count += 1

            event_at = row.business_state_at or row.created_at
            if event_at and _in_window(event_at, period_since, period_until):
                sales_period += fin["total"]
                received_period += fin["received"]
                expected_period += fin["expected"]
                actual_period += fin["actual_received"]
                calculated_period += fin["calculated_received"]
                sales_period_count += 1
                buyers_period.add(int(row.user_id))
                if fin["received"] > 0:
                    received_period_count += 1

        # Відправлення — логістичний показник і навмисно не є продажем.
        shipped_rows = list((await self.s.execute(
            select(m.Order.total, m.Order.created_at).where(m.Order.status.in_(SHIPPED_SQL))
        )).all())
        shipped_total = sum((_dec(row.total) for row in shipped_rows), Decimal(0))
        shipped_period_rows = [
            row for row in shipped_rows
            if row.created_at and _in_window(row.created_at, period_since, period_until)
        ]
        shipped_period = sum((_dec(row.total) for row in shipped_period_rows), Decimal(0))
        shipped_period_count = len(shipped_period_rows)

        active_24h_since = now - timedelta(hours=24)
        customers_total = await self.s.scalar(select(func.count(m.User.id))) or 0
        customers_period = await self.s.scalar(
            select(func.count(m.User.id)).where(
                m.User.created_at >= period_since, m.User.created_at < period_until
            )
        ) or 0
        active_users_period = await self.s.scalar(
            select(func.count(m.User.id)).where(
                m.User.last_seen_at >= period_since, m.User.last_seen_at < period_until
            )
        ) or 0
        active_users_24h = await self.s.scalar(
            select(func.count(m.User.id)).where(m.User.last_seen_at >= active_24h_since)
        ) or 0

        return Stats(
            revenue_total=received_total,
            revenue_period=received_period,
            sales_total=sales_total,
            sales_period=sales_period,
            # Deprecated API aliases: старі клієнти не ламаємо, але семантика
            # тепер та сама, що в sales_* — тільки CRM «Продаж».
            confirmed_total=sales_total,
            confirmed_period=sales_period,
            shipped_total=shipped_total,
            shipped_period=shipped_period,
            expected_total=expected_total,
            expected_period=expected_period,
            actual_received_total=actual_total,
            actual_received_period=actual_period,
            calculated_received_total=calculated_total,
            calculated_received_period=calculated_period,
            orders_total=await self.count_orders(),
            orders_new=await self.count_orders(OrderStatus.NEW),
            customers_total=customers_total,
            customers_period=customers_period,
            active_users_period=int(active_users_period),
            active_users_24h=int(active_users_24h),
            buyers_period=len(buyers_period),
            avg_check=(sales_total / sales_count).quantize(Decimal("0.01"))
            if sales_count else Decimal(0),
            avg_check_period=(sales_period / sales_period_count).quantize(Decimal("0.01"))
            if sales_period_count else Decimal(0),
            # Старий orders_period лишається як compatibility alias для
            # продажів, за якими вже є отримана сума.
            orders_period=received_period_count,
            sales_orders_period=sales_period_count,
            confirmed_orders_period=sales_period_count,
            shipped_orders_period=shipped_period_count,
            low_stock=await self.count_low_stock(),
        )

    async def stats_insights(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None,
        previous_since: datetime | None = None, tz=None,
    ) -> dict:
        """Фінансові зрізи продажів + окрема активність створення замовлень.

        Фінанси, повторні покупки, оплата й доставка використовують момент
        фактичного CRM-продажу (``business_state_at``). Графіки «Коли
        замовляють» принципово інші: вони показують попит і тому відбирають
        *усі* оформлені замовлення за ``created_at`` у вибраному періоді,
        незалежно від того, коли або чи взагалі замовлення стало «Продаж».
        """
        now = datetime.now(timezone.utc)
        span = days if days > 0 else 3650
        period_until = until or now
        period_since = since or (now - timedelta(days=span))
        duration = period_until - period_since
        prev_until = period_since
        prev_since = previous_since if previous_since is not None else period_since - duration
        compare_enabled = since is None or previous_since is not None
        query_since = prev_since if compare_enabled else period_since
        event_expr = func.coalesce(m.Order.business_state_at, m.Order.created_at)

        rows = list((await self.s.execute(
            select(
                m.Order.created_at, m.Order.business_state_at, m.Order.total, m.Order.status,
                m.Order.business_state, m.Order.payment_method, m.Order.delivery_method,
                m.Order.user_id, m.Order.crm_snapshot,
            ).where(
                m.Order.business_state == business.BUSINESS_SALE,
                event_expr >= query_since, event_expr < period_until,
            )
        )).all())

        # Перша покупка визначається моментом фактичного продажу, а не
        # створення заявки. Інакше старе незавершене замовлення, яке продали
        # пізніше, перекручувало new/returning classification.
        first_sale_at = func.coalesce(m.Order.business_state_at, m.Order.created_at)
        first_seen = dict((await self.s.execute(
            select(m.Order.user_id, func.min(first_sale_at))
            .where(m.Order.business_state == business.BUSINESS_SALE)
            .group_by(m.Order.user_id)
        )).all())

        def event_time(row):
            return row.business_state_at or row.created_at

        current = [r for r in rows if event_time(r) and _in_window(event_time(r), period_since, period_until)]
        previous = [
            r for r in rows
            if compare_enabled and event_time(r) and _in_window(event_time(r), prev_since, prev_until)
        ]

        def financial_rows(bucket):
            return [(r, stats_finance_values(
                r.business_state, r.status,
                _stats_payment_method(r, r.crm_snapshot or {}), r.total, r.crm_snapshot,
            )) for r in bucket]

        current_sales = financial_rows(current)
        previous_sales = financial_rows(previous)

        def sum_field(bucket, key):
            return sum((fin[key] for _, fin in bucket), Decimal(0))

        turnover = sum_field(current_sales, "total")
        received = sum_field(current_sales, "received")
        expected = sum_field(current_sales, "expected")
        was_turnover = sum_field(previous_sales, "total")
        was_received = sum_field(previous_sales, "received")
        orders = len(current_sales)
        was_orders = len(previous_sales)

        # «Коли замовляють» — це поведінка оформлення, а не фінансовий
        # результат. Відбираємо всі створені в цьому календарному періоді
        # замовлення за created_at. Інакше замовлення середи, переведене CRM
        # у «Продаж» у четвер, помилково потрапляло б у четвер/період продажу.
        activity_rows = list((await self.s.execute(
            select(m.Order.created_at).where(
                m.Order.created_at >= period_since,
                m.Order.created_at < period_until,
            )
        )).all())
        by_hour = [0] * 24
        by_weekday = [0] * 7
        for activity_row in activity_rows:
            when = _aware(activity_row.created_at)
            if tz is not None:
                when = when.astimezone(tz)
            by_hour[when.hour] += 1
            by_weekday[when.weekday()] += 1

        payment = {
            "card": {"orders": 0, "revenue": Decimal(0), "received": Decimal(0), "expected": Decimal(0)},
            "cod": {"orders": 0, "revenue": Decimal(0), "received": Decimal(0), "expected": Decimal(0)},
        }
        delivery = {"warehouse": 0, "courier": 0, "unknown": 0}
        returning_orders = new_orders = 0
        shipped_orders = 0
        shipped_amount = Decimal(0)

        for row, fin in current_sales:
            method = _stats_payment_method(row, row.crm_snapshot or {})
            slot = payment.get(method)
            if slot is not None:
                slot["orders"] += 1
                slot["revenue"] += fin["total"]
                slot["received"] += fin["received"]
                slot["expected"] += fin["expected"]

            delivery[row.delivery_method if row.delivery_method in delivery else "unknown"] += 1
            if fin["shipped"]:
                shipped_orders += 1
                shipped_amount += fin["total"]

            earliest = first_seen.get(row.user_id)
            sold_at = event_time(row)
            if earliest is not None and sold_at is not None and _aware(earliest) < _aware(sold_at):
                returning_orders += 1
            else:
                new_orders += 1

        refusal_rows = list((await self.s.execute(
            select(m.Order.total, m.Order.business_state_at, m.Order.created_at).where(
                m.Order.business_state == business.BUSINESS_REFUSAL,
                func.coalesce(m.Order.business_state_at, m.Order.created_at) >= period_since,
                func.coalesce(m.Order.business_state_at, m.Order.created_at) < period_until,
            )
        )).all())
        refusals = len(refusal_rows)
        outcomes = orders + refusals

        active_user_ids = set(await self.s.scalars(
            select(m.User.id).where(
                m.User.last_seen_at >= period_since, m.User.last_seen_at < period_until
            )
        ))
        active_users = len(active_user_ids)
        new_users = await self.s.scalar(
            select(func.count(m.User.id)).where(
                m.User.created_at >= period_since, m.User.created_at < period_until
            )
        ) or 0
        active_24h = await self.s.scalar(
            select(func.count(m.User.id)).where(m.User.last_seen_at >= now - timedelta(hours=24))
        ) or 0
        buyer_ids = {int(r.user_id) for r, _ in current_sales}
        unique_buyers = len(buyer_ids)
        active_buyers = len(buyer_ids & {int(uid) for uid in active_user_ids})

        return {
            "days": span,
            "timezone": str(getattr(tz, "key", tz) or "UTC"),
            "period": {"from": period_since.isoformat(), "to": period_until.isoformat()},
            "revenue": {
                "value": float(received), "was": float(was_received),
                "change": _change(received, was_received) if compare_enabled else None,
            },
            "turnover": {
                "value": float(turnover), "was": float(was_turnover),
                "change": _change(turnover, was_turnover) if compare_enabled else None,
            },
            "expected": {"value": float(expected)},
            "orders": {
                "value": orders, "was": was_orders,
                "change": _change(Decimal(orders), Decimal(was_orders)) if compare_enabled else None,
            },
            "shipped": {"orders": shipped_orders, "amount": float(shipped_amount)},
            "avg_check": {
                "value": float(turnover / orders) if orders else 0.0,
                "was": float(was_turnover / was_orders) if was_orders else 0.0,
                "change": _change(
                    turnover / orders if orders else Decimal(0),
                    was_turnover / was_orders if was_orders else Decimal(0),
                ) if compare_enabled else None,
            },
            "repeat": {
                "new_orders": new_orders,
                "returning_orders": returning_orders,
                "share": round(returning_orders * 100 / orders, 1) if orders else 0.0,
            },
            "refusals": {
                "orders": refusals,
                "lost": float(sum((_dec(r.total) for r in refusal_rows), Decimal(0))),
                "share": round(refusals * 100 / outcomes, 1) if outcomes else 0.0,
            },
            # Deprecated compatibility alias for dashboard builds before 1.51.
            "cancelled": {
                "orders": refusals,
                "lost": float(sum((_dec(r.total) for r in refusal_rows), Decimal(0))),
                "share": round(refusals * 100 / outcomes, 1) if outcomes else 0.0,
            },
            "payment": {
                key: {
                    "orders": slot["orders"],
                    "revenue": float(slot["revenue"]),
                    "received": float(slot["received"]),
                    "expected": float(slot["expected"]),
                } for key, slot in payment.items()
            },
            "delivery": delivery,
            "activity": {
                "active_users": int(active_users),
                "active_24h": int(active_24h),
                "new_users": int(new_users),
                "buyers": unique_buyers,
                "active_buyers": active_buyers,
                # Conversion must use an intersection. A manager can move an
                # inactive customer's old order to «Продаж», so dividing all
                # buyers by active users could otherwise exceed 100%.
                "buyer_share": round(active_buyers * 100 / active_users, 1) if active_users else 0.0,
            },
            "by_hour": by_hour,
            "by_weekday": by_weekday,
        }

    async def stats_by_operator(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        period_since = since or (
            now - timedelta(days=days) if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        period_until = until or now
        event_expr = func.coalesce(m.Order.business_state_at, m.Order.created_at)
        rows = list((await self.s.execute(
            select(
                m.Order.operator_name, m.Order.status, m.Order.business_state,
                m.Order.payment_method, m.Order.total, m.Order.crm_snapshot,
            ).where(
                m.Order.business_state == business.BUSINESS_SALE,
                event_expr >= period_since, event_expr < period_until,
            )
        )).all())
        grouped: dict[str, dict] = {}
        for row in rows:
            name = row.operator_name or "Без менеджера"
            fin = stats_finance_values(
                row.business_state, row.status,
                _stats_payment_method(row, row.crm_snapshot or {}), row.total, row.crm_snapshot,
            )
            slot = grouped.setdefault(name, {
                "operator_name": name, "orders": 0, "revenue": Decimal(0),
                "received": Decimal(0), "expected": Decimal(0),
            })
            slot["orders"] += 1
            slot["revenue"] += fin["total"]
            slot["received"] += fin["received"]
            slot["expected"] += fin["expected"]
        result = []
        for slot in grouped.values():
            slot["avg_check"] = (
                slot["revenue"] / slot["orders"]
            ).quantize(Decimal("0.01")) if slot["orders"] else Decimal(0)
            result.append(slot)
        result.sort(key=lambda item: item["revenue"], reverse=True)
        return result

    async def stats_series(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None, tz=None,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        period_since = since or (now - timedelta(days=days))
        period_until = until or now
        event_expr = func.coalesce(m.Order.business_state_at, m.Order.created_at)
        rows = list((await self.s.execute(
            select(
                m.Order.business_state_at, m.Order.created_at, m.Order.total, m.Order.status,
                m.Order.business_state, m.Order.payment_method, m.Order.crm_snapshot,
            ).where(
                m.Order.business_state == business.BUSINESS_SALE,
                event_expr >= period_since, event_expr < period_until,
            )
        )).all())
        buckets: dict[str, dict] = {}
        row_days = []
        for row in rows:
            moment = _aware(row.business_state_at or row.created_at)
            if tz is not None:
                moment = moment.astimezone(tz)
            row_day = moment.date()
            row_days.append(row_day)
            key = row_day.isoformat()
            bucket = buckets.setdefault(key, {
                "date": key, "revenue": Decimal(0), "sales": Decimal(0),
                "confirmed": Decimal(0), "expected": Decimal(0), "orders": 0, "shipped": 0,
            })
            fin = stats_finance_values(
                row.business_state, row.status,
                _stats_payment_method(row, row.crm_snapshot or {}), row.total, row.crm_snapshot,
            )
            bucket["revenue"] += fin["received"]
            bucket["sales"] += fin["total"]
            bucket["confirmed"] += fin["total"]  # deprecated alias
            bucket["expected"] += fin["expected"]
            bucket["orders"] += 1
            if fin["shipped"]:
                bucket["shipped"] += 1

        if not row_days:
            return []
        local_until = period_until.astimezone(tz) if tz is not None else period_until
        end_day = local_until.date()
        local_since = period_since.astimezone(tz) if tz is not None else period_since
        start_day = min(row_days) if local_since.year <= 1971 else local_since.date()
        if start_day > end_day:
            return []

        dense = []
        day = start_day
        while day <= end_day:
            key = day.isoformat()
            dense.append(buckets.get(key, {
                "date": key, "revenue": Decimal(0), "sales": Decimal(0),
                "confirmed": Decimal(0), "expected": Decimal(0), "orders": 0, "shipped": 0,
            }))
            day += timedelta(days=1)
        return dense

    async def stats_top_products(
        self, days: int, limit: int, *, since: datetime | None = None, until: datetime | None = None,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        period_since = since or (
            now - timedelta(days=days) if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        period_until = until or now
        event_expr = func.coalesce(m.Order.business_state_at, m.Order.created_at)
        line_gross = m.OrderItem.price * m.OrderItem.qty
        # Раніше top-products показував gross price×qty і ігнорував знижку
        # замовлення/бонуси, тому його «оборот» був більшим за загальний.
        # Розподіляємо фактичний order.total між позиціями пропорційно gross.
        line_net = case(
            (m.Order.subtotal > 0, line_gross * m.Order.total / m.Order.subtotal),
            else_=Decimal(0),
        )
        net_sum = func.sum(line_net)
        rows = await self.s.execute(
            select(m.OrderItem.name, func.sum(m.OrderItem.qty), net_sum)
            .join(m.Order, m.Order.id == m.OrderItem.order_id)
            .where(
                m.Order.business_state == business.BUSINESS_SALE,
                event_expr >= period_since, event_expr < period_until,
            )
            .group_by(m.OrderItem.name)
            .order_by(net_sum.desc())
            .limit(limit)
        )
        return [{"name": n, "qty": int(q), "revenue": _dec(r).quantize(Decimal("0.01"))} for n, q, r in rows]
