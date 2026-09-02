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
def buttons(payment):
    markup = kb.admin_order(1, payment)
    return [b.callback_data.rsplit(":", 1)[1]
            for row in markup.inline_keyboard for b in row]

card_btn, cod_btn = buttons(CARD), buttons(COD)
r.check("paid" in card_btn, "картка: кнопка «Оплачено» є", card_btn)
r.check("paid" not in cod_btn,
        "накладений платіж: кнопки «Оплачено» немає — вона лише дала б відмову",
        cod_btn)
r.check("confirmed" not in card_btn and "confirmed" not in cod_btn,
        "кнопки «Підтвердити» немає в жодному наборі", card_btn + cod_btn)
for needed in ("accepted", "shipped", "done", "cancelled"):
    r.check(needed in cod_btn, f"накладений платіж: є «{needed}»", cod_btn)
    r.check(needed in card_btn, f"картка: є «{needed}»", card_btn)

print("\n--- кожна кнопка веде до дозволеного переходу ---")
# Інакше менеджер тисне й отримує помилку замість дії.
for payment, names in ((CARD, card_btn), (COD, cod_btn)):
    route = route_for(payment)
    reachable = {s.value for targets in route.values() for s in targets}
    unusable = [n for n in names if n not in reachable]
    r.check(not unusable, f"{payment}: усі кнопки досяжні", unusable)

r.done()
