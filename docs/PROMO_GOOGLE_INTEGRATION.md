# Google integration for promo pages

Promo pages support Google services per page. No global storefront/bot settings are changed.

## Supported integrations

- Google tag / GA4 (`G-*`, `GT-*`, `AW-*`)
- Google Tag Manager (`GTM-*`)
- Google Ads conversion ID + conversion label
- Google Search Console HTML verification token
- Consent Mode v2 (`analytics_storage`, `ad_storage`, `ad_user_data`, `ad_personalization`)
- Built-in consent banner
- `promo_cta_click` event for CTA clicks

## Tagging modes

Use one mode per promo page:

1. **Google tag** — the page loads `gtag.js` once. Page views are collected by the configured Google tag and CTA clicks are sent as `promo_cta_click`. If Ads conversion ID + Label are configured, CTA clicks also fire the Google Ads `conversion` event.
2. **Google Tag Manager** — the page loads only the GTM container. CTA clicks are pushed to `dataLayer` as `promo_cta_click`. Configure GA4 / Google Ads tags and triggers in GTM itself.

The system deliberately does not inject both installation methods at the same time.

## Search Console

Paste only the value from the `content` attribute of Google Search Console's `google-site-verification` meta tag. The renderer creates the meta tag automatically. This can remain active even when analytics tracking is disabled.

## Consent

The recommended mode is the built-in banner. Before consent, Google storage permissions default to denied. The user's decision is stored in `localStorage` and Consent Mode v2 is updated accordingly.

## Security

Managers cannot paste arbitrary HTML or JavaScript. Google IDs are validated server-side and production CSP allows only the Google endpoints used by the integration.
