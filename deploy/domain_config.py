"""Validated main-domain routing shared by render, certificate setup and probes."""
import argparse
from pathlib import Path
import re
from urllib.parse import urlsplit


def domain(value):
    value = value.lower().strip().rstrip('.')
    if len(value) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value):
        raise ValueError('Invalid domain name')
    if '.' not in value or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in value.split('.')):
        raise ValueError('Invalid domain labels')
    return value


def load(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            values[key.strip()] = val.strip().strip('\"\'')
    parsed = urlsplit(values.get('PUBLIC_URL', ''))
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError('PUBLIC_URL must be an HTTP(S) domain URL without credentials or custom port')
    primary = domain(parsed.hostname or '')
    if primary == 'www.elfar.pp.ua':
        primary = 'elfar.pp.ua'
    aliases = ['www.elfar.pp.ua'] if primary == 'elfar.pp.ua' else []
    aliases += re.split(r'[\s,]+', values.get('MAIN_DOMAIN_ALIASES', '').strip())
    aliases = list(dict.fromkeys(domain(v) for v in aliases if v and v.lower().rstrip('.') != primary))
    return primary, aliases


def render(template, primary, aliases):
    primary = domain(primary)
    aliases = [domain(v) for v in aliases]
    blocks = ''
    if aliases:
        names = ' '.join(aliases)
        blocks = f'''
# Trusted historic hosts only. Preserve path/query and POST method; never proxy old hosts.
server {{
    listen 80;
    server_name {names};
    include /etc/nginx/deny.d/*.conf;
    location /.well-known/acme-challenge/ {{ root /var/www/certbot; }}
    location / {{ return 308 https://{primary}$request_uri; }}
}}
server {{
    listen 443 ssl;
    server_name {names};
    ssl_certificate /etc/letsencrypt/live/{primary}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{primary}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    include /etc/nginx/deny.d/*.conf;
    include /etc/nginx/hsts.d/*.conf;
    add_header X-Content-Type-Options nosniff always;
    location / {{ return 308 https://{primary}$request_uri; }}
}}
'''
    return template.replace('__DOMAIN__', primary).replace('__MAIN_ALIAS_SERVERS__', blocks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['primary', 'domains', 'render'])
    parser.add_argument('--env', default='../.env')
    parser.add_argument('--template', default='nginx/app.conf.template')
    parser.add_argument('--output', default='nginx/generated/app.conf')
    args = parser.parse_args()
    try:
        primary, aliases = load(args.env)
        if args.action == 'render':
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Keep inode: compose mounts this file, not its parent directory.
            target.write_text(render(Path(args.template).read_text(), primary, aliases))
        else:
            print(primary if args.action == 'primary' else '\n'.join([primary, *aliases]))
    except ValueError as exc:
        parser.error(str(exc))
