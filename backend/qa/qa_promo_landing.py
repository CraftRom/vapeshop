"""Static contract checks for the promo landing + isolated domain controller."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    router = (ROOT / "backend/api/routers/landing_pages.py").read_text(encoding="utf-8")
    model = (ROOT / "backend/shop/models.py").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/src/pages/LandingPages.jsx").read_text(encoding="utf-8")
    controller = (ROOT / "deploy/promo-controller/controller.py").read_text(encoding="utf-8")
    compose = (ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "draft_config" in model and "published_config" in model
    assert "PromoLandingDailyStat" in model
    assert "local_image" in router and 'path.startswith("/media/")' in router
    assert 'application/ld+json' in router and 'rel="canonical"' in router
    assert 'preview=preview' in router and 'return path if preview' in router
    assert '<base href="${window.location.origin}/">' in page
    assert '/public/go/button' in router and '"clicks"' in router
    assert "require_staff" in router and "domain-connect" in router and "domain-disconnect" in router
    assert "CSS/JS" in page and "SEO" in page and "Статистика" in page
    assert "Підключити домен" in page and "Promo Controller" in page
    assert "Docker socket" in controller and "certbot" in controller
    assert "signal.SIGHUP" in controller and 'os.kill(1' in controller
    assert 'networks: [promo_control]' in compose and 'internal: true' in compose
    assert 'cap_add: ["KILL"]' in compose and 'pid: "service:nginx"' in compose
    assert 'promo-nginx-conf:/promo-conf' in compose and 'promo-nginx-conf:/etc/nginx/promo.d:ro' in compose
    ui = page
    api = (ROOT / "dashboard/src/api.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/src/styles.css").read_text(encoding="utf-8")
    page = router
    assert "generate_seo_payload" in page and "/seo-generate" in page
    assert "_should_generate_initial_seo" in page and "secrets.token_hex" in page
    assert "SEO_HELP" in ui and "SeoLabel" in ui and "Згенерувати SEO" in ui
    assert "generateSeo:" in api and "seo-help-tooltip" in css
    print("promo landing isolation + SEO generator: PASS")


if __name__ == "__main__":
    main()
