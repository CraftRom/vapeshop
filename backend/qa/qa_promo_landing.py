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
    assert 'networks: [promo_control, promo_egress]' in compose and 'internal: true' in compose
    assert 'cap_add: ["KILL"]' in compose and 'pid: "service:nginx"' in compose
    assert 'promo-nginx-conf:/promo-conf' in compose and 'promo-nginx-conf:/etc/nginx/promo.d:ro' in compose
    assert 'PUBLIC_IPV4_OVERRIDE' in controller and 'public_ip_info' in controller and 'api4.ipify.org' in controller
    assert 'autoDetected' in controller and 'dnsRequirements' in controller
    assert 'public_resolver_info' in controller and 'wrongAddresses' in controller and 'propagating' in controller
    assert 'observed_set.issubset(expected_set)' in controller
    assert 'dns_requirements(domain, nameservers)' in controller and 'host = "@"' in controller
    assert 'Налаштування DNS перед деплоєм' in page
    ui = page
    api = (ROOT / "dashboard/src/api.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/src/styles.css").read_text(encoding="utf-8")
    assert "domainStatus: (id, domain)" in api and "form.domain || selected.domain" in ui
    assert "wrongAddresses" in ui and "successfulResolvers" in ui
    page = router
    assert "generate_seo_payload" in page and "/seo-generate" in page
    assert "domain: str | None = None" in page and "target = row.domain if not domain else _domain(domain)" in page
    assert 'if not _BOT_RE.search(request.headers.get("user-agent", ""))' in page
    assert "_should_generate_initial_seo" in page and "secrets.token_hex" in page
    assert "SEO_HELP" in ui and "SeoLabel" in ui and "Згенерувати SEO" in ui
    assert "generateSeo:" in api and "seo-help-tooltip" in css
    print("promo landing isolation + SEO generator: PASS")


if __name__ == "__main__":
    main()
