"""Static contract checks for WebApp requestContact -> bot -> profile bridge.

Runs without aiogram so production checkout regressions remain testable in the
minimal QA container as well.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
shop = (ROOT / "backend/api/routers/shop.py").read_text()
mid = (ROOT / "backend/bot/middlewares.py").read_text()
base = (ROOT / "backend/shop/repo/base.py").read_text()
sql = (ROOT / "backend/shop/repo/sql.py").read_text()
svc = (ROOT / "backend/shop/services/shop_service.py").read_text()
factory = (ROOT / "backend/bot/factory.py").read_text()

checks = {
    "profile exposes own phone": "phone: str | None = None" in shop and "phone=fresh.phone" in shop,
    "light contact endpoint": '@router.get("/contact-phone"' in shop,
    "repository has phone update": "async def set_user_phone" in base and "async def set_user_phone" in sql,
    "self-contact only": 'contact_user_id == tg_user.id' in mid,
    "shared contact persisted": 'set_phone(user.id, saved_phone)' in mid,
    "manual checkout phone persisted": 'set_phone(user.id, contact_phone)' in svc,
    "contact persistence runs before filters": "observer.outer_middleware(RepositoryMiddleware())" in factory,
    "private gate runs before repository": (
        factory.index("observer.outer_middleware(PrivateOnlyMiddleware())")
        < factory.index("observer.outer_middleware(RepositoryMiddleware())")
    ),
    "contact endpoint rereads DB": "fresh = await repo.get_user(user.id) or user" in shop,
    "contact endpoint disables cache": 'response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"' in shop,
}

bad = 0
for label, ok in checks.items():
    print(f"  {'✓' if ok else '✗'} {label}")
    bad += not ok
print(f"\nTELEGRAM CONTACT BRIDGE: {'OK' if not bad else f'FAILED: {bad}'}")
raise SystemExit(1 if bad else 0)
