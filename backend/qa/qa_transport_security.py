from pathlib import Path

root = Path(__file__).resolve().parents[2]
nginx = (root / 'deploy/nginx/app.conf.template').read_text()
limits = (root / 'deploy/nginx/ratelimit.conf').read_text()
checks = {
    'HTTP redirects to HTTPS': 'return 301 https://$host$request_uri;' in nginx,
    'HTTP does not proxy API': 'proxy_pass $' not in nginx[nginx.index('server {\n    listen 80;'):nginx.index('# ---------------------------------------------------------------------- HTTPS')],
    'SalesDrive webhook has dedicated rate limit': 'limit_req zone=webhook' in nginx and 'zone=webhook:10m' in limits,
    'SalesDrive webhook body capped': 'client_max_body_size 256k;' in nginx,
    'Permissions-Policy present': 'add_header Permissions-Policy' in nginx,
    'Cross-domain policy disabled': 'X-Permitted-Cross-Domain-Policies "none"' in nginx,
}
for name, ok in checks.items(): print(('✓' if ok else '✗'), name)
raise SystemExit(0 if all(checks.values()) else 1)
