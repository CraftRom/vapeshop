"""Єдиний довідник статусів відстеження Нової пошти.

SalesDrive може віддати ``statusCode`` без текстового ``status``. Бізнес-логіка
ніколи не повинна залежати від сирого числа або від UI-підпису, тому код
нормалізується тут один раз і використовується read-model, панеллю та
автоматизаціями CRM.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NovaPoshtaStatus:
    code: str
    key: str
    label: str
    short_label: str
    group: str
    terminal: bool
    delivered: bool
    problem: bool
    track: bool
    legacy: bool = False

    def public(self) -> dict:
        data = asdict(self)
        data["shortLabel"] = data.pop("short_label")
        return data


def _s(code: str, key: str, label: str, short: str, group: str, *,
       terminal: bool = False, delivered: bool = False,
       problem: bool = False, track: bool = True, legacy: bool = False) -> NovaPoshtaStatus:
    return NovaPoshtaStatus(code, key, label, short, group, terminal,
                           delivered, problem, track, legacy)


NOVA_POSHTA_STATUSES: dict[str, NovaPoshtaStatus] = {
    "1": _s("1", "created", "ТТН створена. Нова пошта очікує відправлення від відправника.", "ТТН створена", "created"),
    "2": _s("2", "deleted", "ТТН видалена.", "ТТН видалена", "cancelled", terminal=True, problem=True, track=False),
    "3": _s("3", "not_found", "Номер ТТН не знайдено.", "ТТН не знайдена", "problem", problem=True),
    "4": _s("4", "sender_city", "Відправлення знаходиться у місті відправника.", "У місті відправника", "shipping"),
    "41": _s("41", "sender_city_local", "Відправлення знаходиться у місті відправника. Локальна доставка в межах міста.", "Локальна доставка", "shipping"),
    "5": _s("5", "in_transit", "Відправлення прямує до міста отримувача.", "В дорозі", "shipping"),
    "6": _s("6", "recipient_city", "Відправлення прибуло до міста отримувача.", "У місті отримувача", "shipping"),
    "7": _s("7", "warehouse_arrived", "Відправлення прибуло у відділення отримувача.", "У відділенні", "ready"),
    "8": _s("8", "postomat_arrived", "Відправлення завантажено у поштомат.", "У поштоматі", "ready"),
    "9": _s("9", "received", "Відправлення отримано одержувачем.", "Отримано", "delivered", terminal=True, delivered=True, track=False),
    "10": _s("10", "received_money_pending", "Відправлення отримано. Очікується надходження грошового переказу.", "Отримано", "delivered", terminal=True, delivered=True, track=False),
    "11": _s("11", "received_money_paid", "Відправлення отримано. Грошовий переказ видано одержувачу.", "Отримано", "delivered", terminal=True, delivered=True, track=False),
    "12": _s("12", "completing", "Нова пошта комплектує відправлення.", "Комплектується", "processing"),
    "101": _s("101", "courier_delivery", "Відправлення прямує до одержувача.", "Кур'єр доставляє", "delivery"),
    "102": _s("102", "recipient_refusal_return_created", "Відмова від отримання. Створено замовлення на повернення відправнику.", "Відмова / повернення", "returning", problem=True),
    "103": _s("103", "recipient_refusal", "Одержувач відмовився від відправлення.", "Відмова", "returning", problem=True),
    "104": _s("104", "redirected", "Змінено адресу доставки.", "Переадресовано", "shipping"),
    "105": _s("105", "storage_stopped", "Припинено зберігання відправлення.", "Зберігання припинено", "problem", problem=True),
    "106": _s("106", "return_created", "Відправлення отримано та створено нову ТТН зворотної доставки.", "Повернення", "returning", problem=True),
    "111": _s("111", "delivery_failed", "Невдала спроба доставки: одержувач відсутній або з ним немає зв'язку.", "Не вдалося доставити", "problem", problem=True),
    "112": _s("112", "delivery_rescheduled", "Одержувач переніс дату доставки.", "Доставку перенесено", "delivery"),
    # Compatibility зі старішими відповідями API. Не використовуємо для
    # нової бізнес-логіки, але не показуємо користувачу «невідомий код».
    "14": _s("14", "recipient_inspection", "Відправлення передано одержувачу для огляду.", "Огляд відправлення", "ready", legacy=True),
    "108": _s("108", "recipient_refusal_legacy", "Відмова одержувача від отримання.", "Відмова", "returning", problem=True, legacy=True),
}

UNKNOWN_NOVA_POSHTA_STATUS = _s(
    "unknown", "unknown", "Невідомий статус Нової пошти", "Невідомий статус", "unknown"
)

# Автоматизація CRM навмисно вузька: лише явно погоджені коди. Статуси 10/11
# теж означають отримання у довіднику НП, але їх не прирівнюємо до «Продаж»
# без окремого бізнес-рішення.
NOVA_POSHTA_CRM_STATUS_BY_CODE: dict[str, str] = {
    "9": "Продаж",
    "102": "Відмова",
    "103": "Відмова",
}


def get_nova_poshta_status(code) -> NovaPoshtaStatus:
    if code is None:
        return UNKNOWN_NOVA_POSHTA_STATUS
    value = str(code).strip()
    return NOVA_POSHTA_STATUSES.get(value, NovaPoshtaStatus(
        code=value or "unknown",
        key=UNKNOWN_NOVA_POSHTA_STATUS.key,
        label=UNKNOWN_NOVA_POSHTA_STATUS.label,
        short_label=UNKNOWN_NOVA_POSHTA_STATUS.short_label,
        group=UNKNOWN_NOVA_POSHTA_STATUS.group,
        terminal=False,
        delivered=False,
        problem=False,
        track=True,
    ))


def public_nova_poshta_status(code) -> dict:
    return get_nova_poshta_status(code).public()


def crm_status_name_for_nova_poshta(code) -> str | None:
    return NOVA_POSHTA_CRM_STATUS_BY_CODE.get(str(code).strip()) if code is not None else None
