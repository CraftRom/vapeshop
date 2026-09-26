from __future__ import annotations

import hmac
import ipaddress
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
from urllib.request import Request, urlopen

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
TOKEN = os.environ.get("PROMO_CONTROLLER_TOKEN", "").strip()
CERTBOT_EMAIL = os.environ.get("CERTBOT_EMAIL", "").strip()
CONF_DIR = Path(os.environ.get("PROMO_CONF_DIR", "/promo-conf"))
WEBROOT = Path(os.environ.get("PROMO_ACME_WEBROOT", "/var/www/certbot"))
LE_DIR = Path(os.environ.get("PROMO_LE_DIR", "/etc/letsencrypt"))
LISTEN = os.environ.get("PROMO_CONTROLLER_LISTEN", "0.0.0.0")
PORT = int(os.environ.get("PROMO_CONTROLLER_PORT", "8787"))
RENEW_SECONDS = max(3600, int(os.environ.get("PROMO_RENEW_SECONDS", "43200")))
PUBLIC_IPV4_OVERRIDE = os.environ.get("PROMO_PUBLIC_IPV4", "").strip()
PUBLIC_IPV6_OVERRIDE = os.environ.get("PROMO_PUBLIC_IPV6", "").strip()
PUBLIC_IP_CACHE_SECONDS = max(60, int(os.environ.get("PROMO_PUBLIC_IP_CACHE_SECONDS", "600")))
LOCK = threading.Lock()
PUBLIC_IP_LOCK = threading.Lock()
_PUBLIC_IP_CACHE = {"at": 0.0, "ipv4": None, "ipv6": None, "sources": {}, "errors": {}}

IP_ENDPOINTS = {
    4: (
        "https://api4.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://ifconfig.me/ip",
    ),
    6: (
        "https://api6.ipify.org",
        "https://ipv6.icanhazip.com",
    ),
}

NIC_UA_NAMESERVERS = ("ns10.uadns.com", "ns11.uadns.com", "ns12.uadns.com")
DNS_JSON_ENDPOINTS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)


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


def _valid_public_ip(value: str, version: int) -> str | None:
    try:
        addr = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None
    if addr.version != version or not addr.is_global:
        return None
    return str(addr)


def _fetch_public_ip(version: int) -> tuple[str | None, list[str], list[str]]:
    values: list[str] = []
    errors: list[str] = []
    for endpoint in IP_ENDPOINTS[version]:
        try:
            req = Request(endpoint, headers={"User-Agent": "ELFAR-PromoController/1.0"})
            with urlopen(req, timeout=3.5) as response:
                raw = response.read(128).decode("ascii", "ignore").strip()
            value = _valid_public_ip(raw, version)
            if value:
                values.append(value)
            else:
                errors.append(f"{endpoint}: invalid response")
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}")
    if not values:
        return None, [], errors
    # Use the majority result. With only one successful provider, accept it,
    # but expose the source count so the UI can show reduced confidence.
    counts = {value: values.count(value) for value in set(values)}
    chosen = max(counts, key=lambda value: (counts[value], value))
    winners = [value for value, count in counts.items() if count == counts[chosen]]
    if len(winners) > 1:
        return None, values, errors + ["public IP providers disagree"]
    return chosen, values, errors


def public_ip_info(force: bool = False) -> dict:
    now = time.time()
    with PUBLIC_IP_LOCK:
        if not force and now - float(_PUBLIC_IP_CACHE["at"] or 0) < PUBLIC_IP_CACHE_SECONDS:
            return dict(_PUBLIC_IP_CACHE)

        v4_override = _valid_public_ip(PUBLIC_IPV4_OVERRIDE, 4) if PUBLIC_IPV4_OVERRIDE else None
        v6_override = _valid_public_ip(PUBLIC_IPV6_OVERRIDE, 6) if PUBLIC_IPV6_OVERRIDE else None
        v4, v4_sources, v4_errors = (v4_override, [v4_override], []) if v4_override else _fetch_public_ip(4)
        v6, v6_sources, v6_errors = (v6_override, [v6_override], []) if v6_override else _fetch_public_ip(6)

        data = {
            "at": now,
            "detectedAt": datetime.now(timezone.utc).isoformat(),
            "ipv4": v4,
            "ipv6": v6,
            "sources": {
                "ipv4": "override" if v4_override else "auto",
                "ipv6": "override" if v6_override else ("auto" if v6 else "unavailable"),
                "ipv4Responses": v4_sources,
                "ipv6Responses": v6_sources,
            },
            "errors": {"ipv4": v4_errors, "ipv6": v6_errors},
        }
        _PUBLIC_IP_CACHE.clear()
        _PUBLIC_IP_CACHE.update(data)
        return dict(data)


def _doh_ns_query(name: str) -> tuple[list[str], str | None]:
    errors = []
    for endpoint in DNS_JSON_ENDPOINTS:
        try:
            url = f"{endpoint}?name={name}&type=NS"
            req = Request(url, headers={
                "User-Agent": "ELFAR-PromoController/1.0",
                "Accept": "application/dns-json",
            })
            with urlopen(req, timeout=4.0) as response:
                payload = json.loads(response.read(65536).decode("utf-8"))
            answers = payload.get("Answer") or []
            values = sorted({
                str(item.get("data") or "").strip().lower().rstrip(".")
                for item in answers if int(item.get("type") or 0) == 2 and item.get("data")
            })
            if values:
                return values, None
        except Exception as exc:
            errors.append(f"{type(exc).__name__}")
    return [], ", ".join(errors[-2:]) if errors else None


def _doh_address_query(endpoint: str, name: str, rrtype: str) -> tuple[list[str], str | None]:
    qtype = 1 if rrtype == "A" else 28
    try:
        url = f"{endpoint}?name={name}&type={rrtype}"
        req = Request(url, headers={
            "User-Agent": "ELFAR-PromoController/1.0",
            "Accept": "application/dns-json",
        })
        with urlopen(req, timeout=4.0) as response:
            payload = json.loads(response.read(65536).decode("utf-8"))
        answers = payload.get("Answer") or []
        values = []
        for item in answers:
            if int(item.get("type") or 0) != qtype or not item.get("data"):
                continue
            value = _valid_public_ip(str(item.get("data") or ""), 4 if rrtype == "A" else 6)
            if value:
                values.append(value)
        return sorted(set(values)), None
    except Exception as exc:
        return [], f"{type(exc).__name__}"


def public_resolver_info(domain: str) -> dict:
    checks = []
    all_addresses: set[str] = set()
    successful = 0
    for endpoint in DNS_JSON_ENDPOINTS:
        resolver_name = "Cloudflare" if "cloudflare" in endpoint else "Google"
        a, aerr = _doh_address_query(endpoint, domain, "A")
        aaaa, aaaaerr = _doh_address_query(endpoint, domain, "AAAA")
        addresses = sorted(set(a + aaaa))
        if addresses or not (aerr and aaaaerr):
            successful += 1
        all_addresses.update(addresses)
        checks.append({
            "resolver": resolver_name,
            "addresses": addresses,
            "a": a,
            "aaaa": aaaa,
            "error": ", ".join(x for x in (aerr, aaaaerr) if x) or None,
        })
    return {
        "ok": successful > 0,
        "addresses": sorted(all_addresses),
        "checks": checks,
        "successfulResolvers": successful,
    }


def nameserver_info(domain: str) -> dict:
    labels = domain.split(".")
    checked = []
    nameservers: list[str] = []
    zone = domain
    error = None
    # A promo may be a subdomain. Walk upward until we find the authoritative
    # NS zone. Exact-domain NS wins when the registrable domain itself is delegated.
    for offset in range(0, max(1, len(labels) - 1)):
        candidate = ".".join(labels[offset:])
        if candidate.count(".") < 1:
            break
        checked.append(candidate)
        values, err = _doh_ns_query(candidate)
        if values:
            nameservers = values
            zone = candidate
            error = None
            break
        if err:
            error = err

    nic = bool(nameservers) and all(ns.endswith(".uadns.com") or ns == "uadns.com" for ns in nameservers)
    provider = "NIC.UA" if nic else ("Інший DNS-провайдер" if nameservers else "Не визначено")
    if nic:
        action = "NS залишити без змін. DNS-зона обслуговується NIC.UA; змініть тільки A-запис на IP VPS."
    elif nameservers:
        action = "NS не змінюйте автоматично. A/AAAA треба редагувати у DNS-провайдера, якому належать поточні авторитетні NS."
    else:
        action = "Не вдалося визначити авторитетні NS. Не змінюйте NS навмання; перевірте делегування домену в NIC.UA."
    return {
        "ok": bool(nameservers),
        "zone": zone,
        "nameservers": nameservers,
        "provider": provider,
        "isNicUa": nic,
        "expectedNicUa": list(NIC_UA_NAMESERVERS),
        "action": action,
        "checked": checked,
        "error": error,
    }


def dns_info(domain: str) -> dict:
    public = public_ip_info()
    expected = [ip for ip in (public.get("ipv4"), public.get("ipv6")) if ip]
    local_addresses: list[str] = []
    local_error = None
    try:
        rows = socket.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)
        local_addresses = sorted({row[4][0] for row in rows})
    except socket.gaierror as exc:
        local_error = str(exc)

    resolvers = public_resolver_info(domain)
    public_addresses = resolvers.get("addresses") or []
    # Prefer public resolvers for deployment readiness. The container/system resolver
    # can retain an old answer longer and would make the UI lie about propagation.
    observed = public_addresses if resolvers.get("ok") else local_addresses
    expected_set = set(expected)
    observed_set = set(observed)
    matches = sorted(observed_set.intersection(expected_set)) if expected else []
    wrong = sorted(observed_set.difference(expected_set)) if expected else []
    # ALL visible A/AAAA answers must belong to this VPS. One correct record plus one
    # stale/wrong record is not ready: browsers and ACME may hit the wrong address.
    points_here = bool(observed_set) and not wrong and observed_set.issubset(expected_set) if expected else None
    propagating = bool(matches and wrong)
    return {
        "ok": bool(observed),
        "addresses": observed,
        "localAddresses": local_addresses,
        "publicAddresses": public_addresses,
        "error": None if observed else (local_error or "DNS record not found"),
        "expected": expected,
        "matches": matches,
        "wrongAddresses": wrong,
        "pointsHere": points_here,
        "propagating": propagating,
        "resolverChecks": resolvers.get("checks") or [],
        "successfulResolvers": resolvers.get("successfulResolvers", 0),
    }


def dns_requirements(domain: str, nameservers: dict | None = None) -> dict:
    public = public_ip_info()
    ipv4 = public.get("ipv4")
    ipv6 = public.get("ipv6")
    records = []
    host = domain
    ns = nameservers or {}
    zone = (ns.get("zone") or "").lower().rstrip(".")
    if ns.get("isNicUa") and zone:
        if domain == zone:
            host = "@"
        elif domain.endswith("." + zone):
            host = domain[: -(len(zone) + 1)]
    if ipv4:
        records.append({"type": "A", "host": host, "fqdn": domain, "value": ipv4, "required": True})
    if ipv6:
        records.append({"type": "AAAA", "host": host, "fqdn": domain, "value": ipv6, "required": False})
    return {
        "records": records,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "configured": bool(ipv4),
        "autoDetected": public.get("sources", {}).get("ipv4") == "auto",
        "detectedAt": public.get("detectedAt"),
        "source": public.get("sources", {}),
        "detectionErrors": public.get("errors", {}),
        "note": "IPv4 VPS визначається автоматично. У DNS-панелі поле Name/Host може вимагати @ для кореневого домену, коротке ім’я піддомену або повний домен — це залежить від DNS-провайдера. PROMO_PUBLIC_IPV4/PROMO_PUBLIC_IPV6 залишаються лише як ручний override.",
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
    nameservers = nameserver_info(domain)
    cert_valid = cert["present"] and (cert["daysLeft"] is None or cert["daysLeft"] >= 0)
    active = cfg and https_ready and cert_valid
    return {
        "domain": domain,
        "active": active,
        "routePresent": cfg,
        "dns": dns,
        "dnsRequirements": dns_requirements(domain, nameservers),
        "nameservers": nameservers,
        "tls": cert,
        "publicUrl": f"https://{domain}/" if active else None,
    }


def connect(domain: str) -> dict:
    with LOCK:
        dns = dns_info(domain)
        if not dns["ok"]:
            raise RuntimeError("DNS домену ще не резолвиться. Внесіть записи з блоку «Налаштування DNS перед деплоєм» і повторіть перевірку.")
        if dns.get("pointsHere") is False:
            if dns.get("propagating"):
                wrong = ", ".join(dns.get("wrongAddresses") or [])
                expected = ", ".join(dns.get("expected") or [])
                raise RuntimeError(f"DNS поширюється, але частина резолверів ще бачить старі/зайві адреси: {wrong}. Очікуємо лише: {expected}.")
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
