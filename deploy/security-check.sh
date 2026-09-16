#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
fail=0
check_secret(){ local k="$1"; local v; v=$(sed -n "s/^${k}=//p" .env 2>/dev/null | head -1 || true); if [[ -z "$v" || "$v" == change_* ]]; then echo "FAIL: $k"; fail=1; else echo "OK: $k"; fi; }
for k in JWT_SECRET DASHBOARD_PASSWORD POSTGRES_PASSWORD REDIS_PASSWORD DATA_ENCRYPTION_KEY; do check_secret "$k"; done
if grep -R --exclude-dir=.git --exclude='*.md' -nE 'change-me|DASHBOARD_PASSWORD=admin|forwarded-allow-ips=.\*.' backend deploy .env.example 2>/dev/null; then echo 'WARN: знайдені небезпечні шаблони/заглушки'; fi
if grep -R -nE 'ports:.*(5432|6379)|5432:5432|6379:6379' deploy/docker-compose.prod.yml; then echo 'FAIL: DB/Redis exposed'; fail=1; else echo 'OK: DB/Redis internal only'; fi
if grep -q 'set_real_ip_from' deploy/nginx/cloudflare-realip.conf 2>/dev/null \
   && grep -q 'cloudflare-realip.conf' deploy/docker-compose.prod.yml; then
    echo 'OK: nginx бачить справжні адреси з-за Cloudflare'
else
    echo 'FAIL: немає real_ip для Cloudflare — ліміти й бани рахуються на адресу Cloudflare'; fail=1
fi
if [[ -f /etc/fail2ban/jail.d/elfar.conf ]] && grep -q 'nftables\|iptables' /etc/fail2ban/jail.d/elfar.conf; then
    echo 'FAIL: fail2ban банить фаєрволом — за Cloudflare і Docker такий бан не діє (перезапустіть bootstrap.sh)'; fail=1
fi

if awk '/listen 80;/{f=1} /# ---------------------------------------------------------------------- HTTPS/{f=0} f' deploy/nginx/app.conf.template | grep -q 'proxy_pass'; then
  echo 'FAIL: HTTP проксіює застосунок/API — секрети можуть піти без TLS'; fail=1
else
  echo 'OK: HTTP використовується лише для ACME/HTTPS redirect'
fi
if grep -q 'limit_req zone=webhook' deploy/nginx/app.conf.template && grep -q 'zone=webhook:' deploy/nginx/ratelimit.conf; then
  echo 'OK: SalesDrive webhook має окремий rate limit'
else
  echo 'FAIL: SalesDrive webhook без окремого rate limit'; fail=1
fi
exit "$fail"
