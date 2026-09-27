from pathlib import Path

root = Path(__file__).resolve().parents[2]
router = (root / 'backend/api/routers/landing_pages.py').read_text(encoding='utf-8')
controller = (root / 'deploy/promo-controller/controller.py').read_text(encoding='utf-8')
ui = (root / 'dashboard/src/pages/LandingPages.jsx').read_text(encoding='utf-8')
api = (root / 'dashboard/src/api.js').read_text(encoding='utf-8')
security = (root / 'backend/shop/security_log.py').read_text(encoding='utf-8')

checks = {
    'encrypted token storage': 'encrypt_secret(token)' in router and 'decrypt_secret(row.value)' in router,
    'token never returned': 'return {"configured": bool(token)}' in router,
    'cf zone lookup': "'/zones'" in router and '_cf_find_zone' in router,
    'dns record inspection': '/dns_records' in router,
    'ssl mode inspection': '/settings/ssl' in router,
    'proxy origin validation': 'readyForProxyDeploy' in router and 'originMatches' in router,
    'safe DNS sync conflicts': 'кілька A-записів' in router and 'існує CNAME' in router,
    'proxy bypass is internal opt-in': 'allowProxy' in router and 'allow_proxy' in controller,
    'cloudflare UI': 'Cloudflare API' in ui and 'Синхронізувати DNS + Proxy' in ui,
    'api methods': 'cloudflareSync' in api and 'cloudflareStrict' in api,
    'security events': 'promo.cloudflare.dns.synced' in security and 'promo.cloudflare.ssl.strict' in security,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL'), name)
if failed:
    raise SystemExit('Failed: ' + ', '.join(failed))
print('Cloudflare promo integration QA PASS')
