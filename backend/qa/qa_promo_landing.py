"""Static contract checks for the promo landing module.

Does not require a live PostgreSQL/Redis/nginx stack, so it can run in CI before
integration tests. Runtime behavior remains covered by API smoke after deploy.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    router = (ROOT / "backend/api/routers/landing_pages.py").read_text(encoding="utf-8")
    model = (ROOT / "backend/shop/models.py").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/src/pages/LandingPages.jsx").read_text(encoding="utf-8")
    nginx = (ROOT / "deploy/nginx/promo-domain.conf.template").read_text(encoding="utf-8")

    assert "draft_config" in model and "published_config" in model
    assert "PromoLandingDailyStat" in model
    assert "local_image" in router and 'path.startswith("/media/")' in router
    assert 'application/ld+json' in router and 'rel="canonical"' in router
    assert '/public/go/button' in router and '"clicks"' in router
    assert "CSS/JS" in page and "SEO" in page and "Статистика" in page
    assert "location = /go" in nginx and "location /media/" in nginx
    print("promo landing: PASS")


if __name__ == "__main__":
    main()
