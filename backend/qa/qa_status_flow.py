"""СТАТУСИ: маршрут залежить від способу оплати."""
import os
import sys
import tempfile

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_flow_"))

from qa_common import Report                              # noqa: E402

r = Report("СТАТУСИ")

from bot import keyboards as kb                           # noqa: E402
from shop.entities import OrderStatus                     # noqa: E402
from shop.services.shop_service import (                  # noqa: E402
    route_for, transition_error,
)

CARD, COD = "card", "cod"


def path_of(payment):
    """Проходимо маршрут від «Нове» до кінця, щоразу беручи не скасування."""
    route = route_for(payment)
    current, seen = OrderStatus.NEW, [OrderStatus.NEW]
    while True:
        forward = [s for s in route.get(current, set()) if s != OrderStatus.CANCELLED]
        if not forward:
            return seen
        current = forward[0]
        seen.append(current)


print("\n--- маршрут при оплаті карткою ---")
card = path_of(CARD)
r.check(card == [OrderStatus.NEW, OrderStatus.ACCEPTED,
                 OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DONE],
        "нове → прийняте → оплачене → відправлене → виконане",
        [s.value for s in card])

print("\n--- маршрут при накладеному платежі ---")
cod = path_of(COD)
r.check(OrderStatus.PAID not in cod,
        "«Оплачене» відсутнє: клієнт платить при отриманні", [s.value for s in cod])
r.check(cod == [OrderStatus.NEW, OrderStatus.ACCEPTED,
                OrderStatus.SHIPPED, OrderStatus.DONE],
        "нове → прийняте → відправлене → виконане",
        [s.value for s in cod])

print("\n--- заборонені переходи ---")
r.check(transition_error(OrderStatus.ACCEPTED, OrderStatus.PAID, COD) is not None,
        "накладений платіж не можна позначити оплаченим")
r.check(transition_error(OrderStatus.ACCEPTED, OrderStatus.PAID, CARD) is None,
        "карткою — можна")
r.check(transition_error(OrderStatus.NEW, OrderStatus.SHIPPED, CARD) is not None,
        "не можна перестрибнути через прийняття")
r.check(transition_error(OrderStatus.NEW, OrderStatus.CONFIRMED, CARD) is not None,
        "кроку «Підтверджене» більше немає — перейти в нього не можна")
r.check(transition_error(OrderStatus.DONE, OrderStatus.NEW, CARD) is not None,
        "виконане не повертається назад")

print("\n--- скасування доступне до відправки й після ---")
for status in (OrderStatus.NEW, OrderStatus.CONFIRMED, OrderStatus.ACCEPTED,
               OrderStatus.SHIPPED):
    for payment in (CARD, COD):
        r.check(transition_error(status, OrderStatus.CANCELLED, payment) is None,
                f"{status.value}/{payment}: скасування дозволене")

print("\n--- старі замовлення не застрягають ---")
# До поділу маршрутів замовлення з накладеним платежем могло опинитись
# у статусі «Оплачене». Без виходу вперед воно лишилось би там назавжди.
r.check(transition_error(OrderStatus.PAID, OrderStatus.SHIPPED, COD) is None,
        "з «Оплачене» при накладеному платежі є вихід уперед")
# Те саме зі щойно прибраним «Підтверджене»: міграція переводить його в
# «Прийняте», але рядок, якого вона не зачепила, має рухатись далі.
for payment in (CARD, COD):
    r.check(transition_error(OrderStatus.CONFIRMED, OrderStatus.ACCEPTED, payment) is None,
            f"{payment}: зі спадкового «Підтверджене» є вихід уперед")

print("\n--- кнопки під замовленням ---")
def buttons(payment, status):
    markup = kb.admin_order(1, payment, status)
    if markup is None:
        return []
    return [b.callback_data.rsplit(":", 1)[1]
            for row in markup.inline_keyboard for b in row]

# Клавіатура тепер контекстна: старий варіант показував усі статуси відразу,
# через що callback дозволяв зробити shipped -> paid -> shipped (це видно в
# продакшн-лозі 06.09). Під кожним станом мають лишатися тільки переходи,
# які дозволяє той самий route_for, що й API панелі.
for payment in (CARD, COD):
    route = route_for(payment)
    for status, allowed in route.items():
        shown = set(buttons(payment, status))
        expected = {target.value for target in allowed}
        r.check(shown == expected,
                f"{payment}/{status.value}: кнопки точно відповідають маршруту",
                {"shown": sorted(shown), "expected": sorted(expected)})

card_new = buttons(CARD, OrderStatus.NEW)
cod_new = buttons(COD, OrderStatus.NEW)
r.check(card_new == ["accepted", "cancelled"],
        "нове/картка: лише прийняти або скасувати", card_new)
r.check(cod_new == ["accepted", "cancelled"],
        "нове/накладений: лише прийняти або скасувати", cod_new)

card_accepted = buttons(CARD, OrderStatus.ACCEPTED)
cod_accepted = buttons(COD, OrderStatus.ACCEPTED)
r.check("paid" in card_accepted and "shipped" not in card_accepted,
        "картка: після прийняття спочатку оплата", card_accepted)
r.check("paid" not in cod_accepted and "shipped" in cod_accepted,
        "накладений: після прийняття одразу відправлення", cod_accepted)

r.check(buttons(CARD, OrderStatus.DONE) == [],
        "виконане замовлення більше не має активних кнопок")
r.check(buttons(CARD, OrderStatus.CANCELLED) == [],
        "скасоване замовлення більше не має активних кнопок")

print("\n--- бот не обходить правила панелі ---")
_admin = open("bot/handlers/admin.py", encoding="utf-8").read()
r.check("transition_error(order.status, status, order.payment_method)" in _admin,
        "callback перевіряє той самий маршрут, що й API")
r.check("status == OrderStatus.SHIPPED and not tracking" in _admin,
        "через кнопку не можна поставити «Відправлено» без ТТН")
r.check("order.status == status" in _admin,
        "повторне натискання не шле клієнту дубль повідомлення")

r.done()
