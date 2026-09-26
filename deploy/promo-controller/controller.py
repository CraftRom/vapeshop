from __future__ import annotations

import hmac
import json
import os
import re
import signal
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
TOKEN = os.environ.get("PROMO_CONTROLLER_TOKEN", "").strip()
CERTBOT_EMAIL = os.environ.get("CERTBOT_EMAIL", "").strip()
CONF_DIR = Path(os.environ.get("PROMO_CONF_DIR", "/promo-conf"))
WEBROOT = Path(os.environ.get("PROMO_ACME_WEBROOT", "/var/www/certbot"))
LE_DIR = Path(os.environ.get("PROMO_LE_DIR", "/etc/letsencrypt"))
LISTEN = os.environ.get("PROMO_CONTROLLER_LISTEN", "0.0.0.0")
PORT = int(os.environ.get("PROMO_CONTROLLER_PORT", "8787"))
RENEW_SECONDS = max(3600, int(os.environ.get("PROMO_RENEW_SECONDS", "43200")))
PUBLIC_IPV4 = os.environ.get("PROMO_PUBLIC_IPV4", "").strip()
PUBLIC_IPV6 = os.environ.get("PROMO_PUBLIC_IPV6", "").strip()
LOCK = threading.Lock()


def normalize_domain(value: str) -> str:
    value = (value or "").strip().lower().rstrip(".")
    if value.startswith("http://") or value.startswith("https://"):
        value = (urlparse(value).hostname or "").lower()
    if not DOMAIN_RE.fullmatch(value):
        raise ValueError("Некоректний домен")
    return value


def config_path(domain: str) -> Path:
    return CONF_DIR / f"{domain}.conf"


def live_dir(domain: str) -> Path:
    return LE_DIR / "live" / domain


def cert_exists(domain: str) -> bool:
    root = live_dir(domain)
    return (root / "fullchain.pem").exists() and (root / "privkey.pem").exists()


def cert_info(domain: str) -> dict:
    path = live_dir(domain) / "cert.pem"
    if not path.exists():
        return {"present": False, "expiresAt": None, "daysLeft": None}
    try:
        decoded = ssl._ssl._test_decode_cert(str(path))
        raw = decoded.get("notAfter")
        expires = datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = int((expires - datetime.now(timezone.utc)).total_seconds() // 86400)
        return {"present": True, "expiresAt": expires.isoformat(), "daysLeft": days}
    except Exception:
        return {"present": True, "expiresAt": None, "daysLeft": None}


def dns_info(domain: str) -> dict:
    expected = [ip for ip in (PUBLIC_IPV4, PUBLIC_IPV6) if ip]
    try:
        rows = socket.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)
        addresses = sorted({row[4][0] for row in rows})
        matches = sorted(set(addresses).intersection(expected)) if expected else []
        points_here = bool(matches) if expected else None
        return {
            "ok": bool(addresses),
            "addresses": addresses,
            "error": None,
            "expected": expected,
            "matches": matches,
            "pointsHere": points_here,
        }
    except socket.gaierror as exc:
        return {
            "ok": False, "addresses": [], "error": str(exc),
            "expected": expected, "matches": [], "pointsHere": False if expected else None,
        }


def dns_requirements(domain: str) -> dict:
    records = []
    if PUBLIC_IPV4:
        records.append({"type": "A", "host": domain, "value": PUBLIC_IPV4, "required": True})
    if PUBLIC_IPV6:
        records.append({"type": "AAAA", "host": domain, "value": PUBLIC_IPV6, "required": False})
    return {
        "records": records,
        "ipv4": PUBLIC_IPV4 or None,
        "ipv6": PUBLIC_IPV6 or None,
        "configured": bool(records),
        "note": "У DNS-панелі поле Name/Host може вимагати @ для кореневого домену, коротке ім’я піддомену або повний домен — це залежить від DNS-провайдера.",
    }


def nginx_reload() -> None:
    # Controller shares ONLY nginx' PID namespace. PID 1 is nginx master.
    # No Docker socket is mounted and the controller cannot start/exec containers.
    os.kill(1, signal.SIGHUP)
    time.sleep(0.35)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def http_config(domain: str) -> str:
    return f'''# Managed by isolated promo-controller. Do not edit.\nserver {{\n    listen 80;\n    server_name {domain};\n    include /etc/nginx/deny.d/*.conf;\n    location /.well-known/acme-challenge/ {{ root /var/www/certbot; }}\n    location / {{ default_type text/plain; return 503 "Домен готується до публікації\\n"; }}\n}}\n'''


def https_config(domain: str) -> str:
    return f'''# Managed by isolated promo-controller. Do not edit.\nserver {{\n    listen 80;\n    server_name {domain};\n    include /etc/nginx/deny.d/*.conf;\n    location /.well-known/acme-challenge/ {{ root /var/www/certbot; }}\n    location / {{ return 301 https://$host$request_uri; }}\n}}\n\nserver {{\n    listen 443 ssl;\n    http2 on;\n    server_name {domain};\n    include /etc/nginx/deny.d/*.conf;\n\n    ssl_certificate     /etc/letsencrypt/live/{domain}/fullchain.pem;\n    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n    ssl_protocols TLSv1.2 TLSv1.3;\n    ssl_session_cache shared:SSL:10m;\n    ssl_session_timeout 1d;\n\n    add_header X-Content-Type-Options "nosniff" always;\n    add_header X-Frame-Options "DENY" always;\n    add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;\n    add_header Content-Security-Policy "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none';" always;\n\n    location /media/ {{\n        alias /data/media/;\n        access_log off;\n        expires 30d;\n        add_header Cache-Control "public, immutable";\n        add_header X-Content-Type-Options "nosniff" always;\n        location ~* \\.(php|py|sh|html?)$ {{ deny all; }}\n    }}\n\n    location = /go {{\n        limit_req zone=api burst=20 nodelay;\n        proxy_pass http://api:8000/api/landing-pages/public/go/button;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto $scheme;\n    }}\n\n    location = /robots.txt {{\n        default_type text/plain;\n        return 200 "User-agent: *\\nAllow: /\\n";\n    }}\n\n    location = / {{\n        limit_req zone=api burst=20 nodelay;\n        proxy_pass http://api:8000/api/landing-pages/public/render/page;\n        proxy_set_header Host $host;\n        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_read_timeout 30s;\n    }}\n\n    location / {{ return 404; }}\n}}\n'''


def run_certbot(domain: str) -> tuple[bool, str]:
    cmd = [
        "certbot", "certonly", "--webroot", "-w", str(WEBROOT),
        "--cert-name", domain, "-d", domain,
        "--non-interactive", "--agree-tos",
        "--config-dir", str(LE_DIR), "--work-dir", "/tmp/letsencrypt-work", "--logs-dir", "/tmp/letsencrypt-logs",
        "--keep-until-expiring", "--preferred-challenges", "http",
    ]
    if CERTBOT_EMAIL:
        cmd += ["--email", CERTBOT_EMAIL]
    else:
        # Домен можна підключити з панелі навіть без попереднього ручного
        # налаштування email у .env. За наявності CERTBOT_EMAIL certbot
        # використовує його для сповіщень про сертифікати.
        cmd += ["--register-unsafely-without-email"]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        # Не виводимо весь certbot log у панель: у ньому можуть бути технічні шляхи.
        tail = " | ".join(output.splitlines()[-4:])[:700]
        return False, tail or f"certbot завершився з кодом {proc.returncode}"
    return True, "TLS-сертифікат готовий"


def status(domain: str) -> dict:
    path = config_path(domain)
    cfg = path.exists()
    https_ready = False
    if cfg:
        try:
            https_ready = "listen 443 ssl" in path.read_text(encoding="utf-8")
        except OSError:
            https_ready = False
    cert = cert_info(domain)
    dns = dns_info(domain)
    cert_valid = cert["present"] and (cert["daysLeft"] is None or cert["daysLeft"] >= 0)
    active = cfg and https_ready and cert_valid
    return {
        "domain": domain,
        "active": active,
        "routePresent": cfg,
        "dns": dns,
        "dnsRequirements": dns_requirements(domain),
        "tls": cert,
        "publicUrl": f"https://{domain}/" if active else None,
    }


def connect(domain: str) -> dict:
    with LOCK:
        dns = dns_info(domain)
        if not dns["ok"]:
            raise RuntimeError("DNS домену ще не резолвиться. Внесіть записи з блоку «Налаштування DNS перед деплоєм» і повторіть перевірку.")
        if dns.get("pointsHere") is False:
            raise RuntimeError("Домен резолвиться, але веде не на цей VPS. Перевірте значення A/AAAA у блоці «Налаштування DNS перед деплоєм».")

        path = config_path(domain)
        write_atomic(path, http_config(domain))
        nginx_reload()

        info = cert_info(domain)
        # Сертифікат, якому лишилося <30 днів, одразу віддаємо certbot:
        # він або продовжить його, або підтвердить, що чинний ще достатньо.
        needs_cert = (not info["present"] or info["daysLeft"] is None or info["daysLeft"] < 30)
        if needs_cert:
            ok, detail = run_certbot(domain)
            if not ok:
                # HTTP route лишається для наступної повторної спроби ACME, але production не активний.
                raise RuntimeError(f"Не вдалося отримати TLS: {detail}")

        write_atomic(path, https_config(domain))
        nginx_reload()
        return status(domain)


def disconnect(domain: str) -> dict:
    with LOCK:
        path = config_path(domain)
        if path.exists():
            path.unlink()
            nginx_reload()
        # Сертифікат свідомо не видаляємо: це дає безпечний rollback/reconnect.
        return status(domain)


def renew_loop() -> None:
    while True:
        time.sleep(RENEW_SECONDS)
        try:
            with LOCK:
                proc = subprocess.run(
                    ["certbot", "renew", "--webroot", "-w", str(WEBROOT),
                     "--config-dir", str(LE_DIR), "--work-dir", "/tmp/letsencrypt-work",
                     "--logs-dir", "/tmp/letsencrypt-logs", "--quiet"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600,
                )
                # HUP безпечний і при відсутності renew; він перечитує сертифікати/конфіги атомарно.
                if proc.returncode == 0:
                    nginx_reload()
        except Exception as exc:
            print(f"promo-controller renew error: {type(exc).__name__}: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "PromoController/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print("promo-controller", fmt % args, flush=True)

    def send_json(self, status_code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self) -> bool:
        if not TOKEN:
            return False
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
        return hmac.compare_digest(header.encode(), expected.encode())

    def read_body(self) -> dict:
        length = min(int(self.headers.get("Content-Length", "0") or 0), 8192)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        if self.path == "/health":
            return self.send_json(200, {"ok": True, "tokenConfigured": bool(TOKEN), "emailConfigured": bool(CERTBOT_EMAIL)})
        if not self.authorized():
            return self.send_json(401, {"detail": "unauthorized"})
        if self.path.startswith("/v1/status?"):
            from urllib.parse import parse_qs, urlsplit
            qs = parse_qs(urlsplit(self.path).query)
            try:
                domain = normalize_domain((qs.get("domain") or [""])[0])
                return self.send_json(200, status(domain))
            except ValueError as exc:
                return self.send_json(400, {"detail": str(exc)})
        return self.send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        if not self.authorized():
            return self.send_json(401, {"detail": "unauthorized"})
        try:
            body = self.read_body()
            domain = normalize_domain(body.get("domain", ""))
            if self.path == "/v1/connect":
                return self.send_json(200, connect(domain))
            if self.path == "/v1/disconnect":
                return self.send_json(200, disconnect(domain))
            return self.send_json(404, {"detail": "not found"})
        except ValueError as exc:
            return self.send_json(400, {"detail": str(exc)})
        except subprocess.TimeoutExpired:
            return self.send_json(504, {"detail": "ACME/TLS операція перевищила допустимий час"})
        except RuntimeError as exc:
            return self.send_json(409, {"detail": str(exc)})
        except Exception as exc:
            print(f"promo-controller request error: {type(exc).__name__}: {exc}", flush=True)
            return self.send_json(500, {"detail": "Внутрішня помилка контролера доменів"})


if __name__ == "__main__":
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=renew_loop, name="cert-renew", daemon=True).start()
    server = ThreadingHTTPServer((LISTEN, PORT), Handler)
    print(f"promo-controller listening on {LISTEN}:{PORT}", flush=True)
    server.serve_forever()
