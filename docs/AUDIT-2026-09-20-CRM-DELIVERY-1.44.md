# CRM delivery/API audit — 1.44.0

Версії: Dashboard **1.44.0**, API **1.10.0**, Bot **1.12.0**.

## Виправлено

- `ord_delivery_data` у `/api/order/list/` читається як масив, а не лише як dict.
- `provider=novaposhta` + `trackingNumber`/`trackingNumberRef` стають ТТН і Ref замовлення.
- `shipping_costs` використовується як fallback вартості для єдиної накладної.
- Додано `primaryContact`, `shipping_address`, `updateAt` та актуальні назви товарів (`nameTranslate`/`text`/`documentName`).
- Webhook merge оновлює carrier snapshot і для `ord_delivery_data`.
- CRM delivery block показує перевізника, ТТН, Ref, адресу, вартість, статус/код і дані відділення.
- Етапи CRM переведено на адаптивну сітку без горизонтального scroll.

## Перевірки

- `qa_salesdrive_rich_read.py`: 25/25.
- `qa_crm_live_sync.py`: 18/18.
- `qa_salesdrive_read_side.py`: 6/6.
- `qa_crm_status_authority.py`: 14/14.
- SalesDrive dictionaries/no-backfill/source guard: OK.
- усі Dashboard `.mjs` тести: OK; `order-live-sync`: 14/14.
- `python -m compileall backend/shop backend/api`: OK.
