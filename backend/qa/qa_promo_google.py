"""Static regression contracts for Google integrations in promo pages only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    router = (ROOT / "backend/api/routers/landing_pages.py").read_text(encoding="utf-8")
    ui = (ROOT / "dashboard/src/pages/LandingPages.jsx").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/src/styles.css").read_text(encoding="utf-8")
    controller = (ROOT / "deploy/promo-controller/controller.py").read_text(encoding="utf-8")

    # Config is embedded in the page JSON snapshot: no global schema/database change.
    assert "DEFAULT_GOOGLE" in router and "class GoogleIn(BaseModel)" in router
    assert '"google": data.google.model_dump()' in router

    # No arbitrary script injection: only validated Google IDs/tokens are accepted.
    assert "_GOOGLE_TAG_RE" in router and "_GTM_RE" in router and "_ADS_ID_RE" in router
    assert "_ADS_LABEL_RE" in router and "_VERIFY_RE" in router
    assert "google_tag_id" in router and "gtm_container_id" in router

    # Production renderer: one selected tagging strategy, Search Console and Consent Mode v2.
    assert "def _google_markup" in router
    assert "googletagmanager.com/gtag/js" in router
    assert "googletagmanager.com/gtm.js" in router
    assert "google-site-verification" in router
    for signal in ("analytics_storage", "ad_storage", "ad_user_data", "ad_personalization"):
        assert signal in router
    assert "promo_cta_click" in router and "send_to" in router and "event_callback" in router
    assert "preview or not google.get(\"enabled\")" in router

    # Manager UI is page-scoped and explains Google tag vs GTM instead of mixing both blindly.
    assert "DEFAULT_GOOGLE" in ui and "GOOGLE_HELP" in ui
    assert "Google tag / GA4 / Google Ads" in ui and "Google Tag Manager" in ui
    assert "Google Search Console" in ui and "Conversion ID" in ui and "Conversion Label" in ui
    assert "Вбудований банер — рекомендовано" in ui
    assert "promo-google-summary" in css

    # Promo nginx CSP explicitly allows only the Google endpoints required by these integrations.
    assert "https://www.googletagmanager.com" in controller
    assert "https://www.googleadservices.com" in controller
    assert "https://*.google-analytics.com" in controller
    assert "frame-src https://www.googletagmanager.com" in controller

    print("promo Google integrations: PASS")


if __name__ == "__main__":
    main()
