#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0
check_secret(){ local k="$1"; local v; v=$(sed -n "s/^${k}=//p" .env 2>/dev/null | head -1 || true); if [[ -z "$v" || "$v" == change_* ]]; then echo "FAIL: $k"; fail=1; else echo "OK: $k"; fi; }
for k in JWT_SECRET DASHBOARD_PASSWORD POSTGRES_PASSWORD REDIS_PASSWORD DATA_ENCRYPTION_KEY; do check_secret "$k"; done
if grep -R --exclude-dir=.git --exclude='*.md' -nE 'change-me|DASHBOARD_PASSWORD=admin|forwarded-allow-ips=.\*.' backend deploy .env.example 2>/dev/null; then echo 'WARN: знайдені небезпечні шаблони/заглушки'; fi
if grep -R -nE 'ports:.*(5432|6379)|5432:5432|6379:6379' deploy/docker-compose.prod.yml; then echo 'FAIL: DB/Redis exposed'; fail=1; else echo 'OK: DB/Redis internal only'; fi
exit "$fail"
