# Promo pages: Cloudflare API integration

## Purpose

Cloudflare proxied DNS intentionally hides the origin VPS address. Public A/AAAA queries return Cloudflare edge addresses, so direct DNS equality checks are invalid for orange-cloud records.

The promo module therefore uses two verification paths:

- **Direct DNS**: public A/AAAA must resolve only to the detected VPS addresses.
- **Cloudflare Proxy**: the backend verifies the exact Cloudflare DNS record through the authenticated Cloudflare API and confirms that its hidden `content` equals the VPS IPv4 and that `proxied=true`.

## Token storage

The Cloudflare API Token is entered by an administrator in the promo deploy UI. It is verified before save, encrypted with the project's existing `DATA_ENCRYPTION_KEY`, stored in the existing `settings` table, and never returned to the browser. The UI only receives `configured: true/false`.

Recommended permissions:

- Zone / Zone / Read
- Zone / DNS / Edit (also permits DNS reads)
- Zone / Zone Settings / Read
- Zone / Zone Settings / Edit only when the UI should be allowed to switch SSL mode to Full (strict)

Scope the token to only the zones used for promo pages whenever possible.

## Safe DNS synchronization

The `Synchronize DNS + Proxy` action:

1. Detects the matching Cloudflare zone.
2. Detects the VPS public IPv4 using Promo Controller status.
3. Refuses to change a hostname that has a CNAME.
4. Refuses to merge multiple A records automatically.
5. Creates or updates the single A record to the VPS IPv4.
6. Sets `proxied=true` and Cloudflare TTL `Auto` (`ttl=1`).
7. Re-reads the record through Cloudflare API before deployment proceeds.

The system deliberately does not delete unrelated AAAA/MX/TXT/CNAME records.

## TLS

The module reads `/zones/{zone_id}/settings/ssl` and reports the current Cloudflare encryption mode. The administrator can explicitly request `Full (strict)` when the token has Zone Settings Edit permission.

The nginx origin still receives its own certificate. Cloudflare Proxy is not treated as a substitute for origin TLS.

## Deployment trust boundary

Promo Controller has no Cloudflare API token. When a proxied record is validated, the backend sends only `allowProxy=true` over the isolated authenticated promo-control network. Promo Controller then permits the normal route/TLS workflow even though public DNS contains Cloudflare edge IPs rather than the VPS IP.
