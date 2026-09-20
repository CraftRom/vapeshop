# ELFAR 1.51.1 — live CRM sync / chat refresh / log fixes

- Background SalesDrive read-side refresh no longer depends on opening an order.
- Nova Poshta `statusCode=9` drives CRM to `Продаж`; `102/103` drive it to `Відмова`.
- CRM status + business_state are committed through one repository transaction path.
- Dashboard order/support chats and storefront chat refresh silently; storefront chat uses delta polling.
- Storefront also silently refreshes orders/profile/cart/config while visible and online.
- Telegram `@username` is never used as a recipient given name; invalid historical profile first names are nulled by migration while username remains intact.
- Nova Poshta directory uses request coalescing, stale-cache fallback and a short outage circuit breaker.
- Existing PostgreSQL cart row-lock fix is retained; uploaded 500 telemetry came from storefront 2.15.0, while this release ships storefront 2.16.0.
- Foreign SalesDrive webhook rejection remains fail-closed by design; Telegram `Bad Gateway` remains handled by the bot polling retry.
