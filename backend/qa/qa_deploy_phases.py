from pathlib import Path

p = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"
s = p.read_text(encoding="utf-8")
required = [
    "ФАЗА 1/6: базові сервіси",
    "ФАЗА 2/6: міграції БД",
    "ФАЗА 3/6: API",
    "ФАЗА 4/6: основні застосунки",
    "ФАЗА 5/6: nginx основного сайту",
    "ФАЗА 6/6: промо-система",
    "Фінальний API health: OK",
]
pos = [s.index(x) for x in required]
assert pos == sorted(pos), "deploy phases are out of order"
assert "up -d --remove-orphans" not in s, "global up/remove-orphans must not return"
assert "up -d --no-deps --force-recreate nginx" in s, "nginx must be recreated after api"
assert "Promo Controller health" in s
assert "rollback_core_runtime" in s
print("deploy phased regression: PASS")
