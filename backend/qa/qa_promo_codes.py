"""Promo form/API boundaries, expiry, duplicate recovery and customer eligibility."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from qa_common import Report, boot
from qa_paths import qa_db_path

app, Session, _ = boot(qa_db_path("qa_promo_codes.db"))
from shop.repo.base import PromoCodeConflict
from shop.repo.sql import SqlRepository
from shop.services.shop_service import check_promo

c = TestClient(app)
r = Report("Promo codes")
auth = c.post("/api/auth/login", json={"login": "admin", "password": "secret"}).json()
headers = {"Authorization": "Bearer " + auth["access_token"]}
base = {"code": "WELCOME", "type": "percent", "value": "10.25"}

def create(**changes):
    return c.post("/api/promos", headers=headers, json={**base, **changes})

def aware(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date

first = create(code=" welcome ")
r.check(first.status_code == 201 and first.json()["code"] == "WELCOME", "trim and uppercase before saving", first.text)
first = first.json()
r.check(first["max_uses"] is None and first["per_user_limit"] == 1, "unlimited total/default per-customer limit")
r.check(create(code="wElCoMe").status_code == 409, "case-insensitive duplicate rejected")

invalid = [
    {"code": "  "}, {"code": " A "}, {"code": "BAD CODE"}, {"code": "X" * 33},
    {"value": "0"}, {"value": "-1"}, {"value": "100.01"}, {"value": "1.001"},
    {"value": "NaN"}, {"type": "fixed", "value": "10000000000"},
    {"min_order": "-0.01"}, {"min_order": "1.001"},
    {"max_uses": 0}, {"max_uses": -1}, {"max_uses": 1.5}, {"max_uses": 2147483648},
    {"per_user_limit": 0}, {"per_user_limit": 1.5}, {"per_user_limit": 2147483648},
    {"expires_on": "2026-02-30"}, {"expires_on": "9999-12-31"},
    {"expires_at": "2026-12-01T00:00:00"},
    {"expires_on": "2026-12-01", "expires_at": "2026-12-01T00:00:00Z"},
]
for i, values in enumerate(invalid):
    response = create(**{"code": f"BAD{i}", **values})
    r.check(response.status_code == 422, f"invalid input rejected: {values}", response.text)

for day, expected in [
    ("2026-01-10", "2026-01-10T21:59:59.999999+00:00"),
    ("2026-07-10", "2026-07-10T20:59:59.999999+00:00"),
    ("2026-03-29", "2026-03-29T20:59:59.999999+00:00"),
    ("2026-10-25", "2026-10-25T21:59:59.999999+00:00"),
]:
    response = create(code=f"DATE{day}", expires_on=day)
    r.check(response.status_code == 201 and aware(response.json()["expires_at"]) == datetime.fromisoformat(expected),
            f"Kyiv inclusive end of day {day}", response.text)
    r.check("expires_on" not in response.json(), "input-only date not stored/exposed")

fixed = create(code="FIXED", type="fixed", value="250.50", min_order="100", max_uses=2).json()
other = create(code="OTHER").json()
response = c.put(f'/api/promos/{other["id"]}', headers=headers, json={**base, "code": "fixed"})
r.check(response.status_code == 409, "rename duplicate returns 409 instead of 500", response.text)
response = c.put(f'/api/promos/{first["id"]}', headers=headers, json={**base, "code": "welcome", "expires_at": None})
r.check(response.status_code == 200 and response.json()["expires_at"] is None, "edit same code and remove expiry")
create(code="EXPIRED", expires_on="2024-01-01")
create(code="DISABLED", is_active=False)

async def customer_rules():
    async with Session() as session:
        repo = SqlRepository(session)
        user = await repo.create_user(771101, None, "QA", None)
        another = await repo.create_user(771102, None, "QA", None)
        result = await check_promo(repo, "welcome", user.id, Decimal("199.90"))
        r.check(result.ok and result.discount == Decimal("20.49"), "percentage rounded to cents")
        result = await check_promo(repo, "FIXED", user.id, Decimal("99.99"))
        r.check(not result.ok and "Мінімальна" in result.error, "minimum order enforced")
        result = await check_promo(repo, "FIXED", user.id, Decimal("100"))
        r.check(result.ok and result.discount == 100, "minimum boundary accepted; discount capped at subtotal")
        for code in ["EXPIRED", "DISABLED"]:
            result = await check_promo(repo, code, user.id, Decimal("1000"))
            r.check(not result.ok, f"{code} unavailable to customers")
        await repo.register_promo_use(fixed["id"], user.id, None)
        result = await check_promo(repo, "FIXED", user.id, Decimal("1000"))
        r.check(not result.ok and "вже використали" in result.error, "per-customer limit enforced")
        result = await check_promo(repo, "FIXED", another.id, Decimal("1000"))
        r.check(result.ok and result.discount == Decimal("250.50"), "another customer can use fixed discount")
        await repo.register_promo_use(fixed["id"], another.id, None)
        result = await check_promo(repo, "FIXED", another.id, Decimal("1000"))
        r.check(not result.ok and "Ліміт" in result.error, "total usage limit enforced")
        # Exercise the database conflict/rollback path used when the API precheck races.
        for update in [False, True]:
            try:
                if update:
                    await repo.update_promo(other["id"], {"code": "welcome"})
                else:
                    await repo.create_promo({"code": "welcome", "value": Decimal("5")})
                r.check(False, "database duplicate translated")
            except PromoCodeConflict:
                r.check(True, f"database {'update' if update else 'create'} conflict translated")
            r.check(bool(await repo.get_promo(first["id"])), "session usable after duplicate rollback")

asyncio.run(customer_rules())
r.check(c.get("/api/promos", headers=headers).status_code == 200, "list still readable after all rejected writes")
c.close()
asyncio.run(Session.kw["bind"].dispose())
raise SystemExit(bool(r.done()))
