"""Regression: SalesDrive dictionaries and optional Telegram formId."""
from api.schemas import ShopSettingsIn
from api.routers.integrations import _dictionary_items

assert ShopSettingsIn(salesdrive_telegram_form_id=0).salesdrive_telegram_form_id is None
assert ShopSettingsIn(salesdrive_telegram_form_id="").salesdrive_telegram_form_id is None
assert ShopSettingsIn(salesdrive_telegram_form_id=7).salesdrive_telegram_form_id == 7
assert _dictionary_items({"data": [{"id": 1, "name": "Нове"}]}) == [{"id": "1", "name": "Нове"}]
assert _dictionary_items([{"value": "cod", "label": "Післяплата"}]) == [{"id": "cod", "name": "Післяплата"}]
print("✓ SalesDrive dictionaries/formId: 5/5")
