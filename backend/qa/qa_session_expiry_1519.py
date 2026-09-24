from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
auth = (ROOT / "api/webapp_auth.py").read_text(encoding="utf-8")
security = (ROOT / "shop/security_log.py").read_text(encoding="utf-8")
mini_api = (ROOT.parent / "miniapp/src/api.js").read_text(encoding="utf-8")
app = (ROOT.parent / "miniapp/src/App.jsx").read_text(encoding="utf-8")
main = (ROOT.parent / "miniapp/src/main.jsx").read_text(encoding="utf-8")

checks = [
    ("expired initData has dedicated security event", "security.initdata.expired" in auth and "security.initdata.expired" in security),
    ("expired initData is info, not suspicious notice", '_e("security.initdata.expired", "info"' in security),
    ("auth backend logs expired/missing below warning", "log.info if (expired or missing) else log.warning" in auth),
    ("miniapp has terminal auth-failure event", "AUTH_FAILURE_EVENT = 'elfar:auth-failure'" in mini_api),
    ("first 401 stops normal request flow", "if (res.status === 401)" in mini_api and "signalAuthFailure(detail)" in mini_api),
    ("SSE 401 also terminates auth loop", "consumeOrderEvents" in mini_api and "throw authFailureError(detail)" in mini_api),
    ("app clears active data after auth failure", "setConfig(null)" in app and "setOrders([])" in app and "AUTH_FAILURE_EVENT" in app),
    ("realtime does not reconnect after auth 401", "err?.authFailure || err?.status === 401" in app),
    ("hidden WebView disconnect is not warning noise", "if (!document.hidden && navigator.onLine !== false)" in app),
    ("successful legacy www bridge is informational", "level: initData ? 'info' : 'warning'" in main),
]
failed = 0
for name, ok in checks:
    print(("✓" if ok else "✗"), name)
    failed += 0 if ok else 1
print(f"\nSESSION EXPIRY QA: {len(checks)-failed}/{len(checks)}")
sys.exit(1 if failed else 0)
