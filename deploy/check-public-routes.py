#!/usr/bin/env python3
"""Read-only main/legacy route gate. External mode validates DNS and trusted TLS."""
import argparse
import http.client
import json
import re
import socket
import ssl
import sys
from urllib.parse import urlsplit
from domain_config import load


class OriginHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, port, context):
        super().__init__(host, port, timeout=8, context=context)
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def run(args):
    primary, aliases = load(args.env)
    context = ssl.create_default_context() if args.external or args.ca_file else ssl._create_unverified_context()
    if args.ca_file:
        context.load_verify_locations(args.ca_file)

    def get(host, path, secure=True):
        if secure:
            connection = OriginHTTPS(host, host if args.external else args.address, args.https_port, context)
        else:
            connection = http.client.HTTPConnection(host if args.external else args.address, args.http_port, timeout=8)
        try:
            connection.request('GET', path, headers={'Host': host, 'User-Agent': 'ELFAR-route-check/1.0'})
            response = connection.getresponse()
            body = response.read(2 * 1024 * 1024)
            return response.status, dict((k.lower(), v) for k, v in response.getheaders()), body
        finally:
            connection.close()

    def require(ok, host, path, result):
        status, headers, _ = result
        if not ok:
            # Do not print response bodies, query tokens or webhook URLs.
            raise RuntimeError(f'{host} {urlsplit(path).path}: status={status}, cf-ray={headers.get("cf-ray", "none")}')

    health = get(primary, '/api/health')
    require(health[0] == 200 and 'application/json' in health[1].get('content-type', ''), primary, '/api/health', health)
    if not isinstance(json.loads(health[2]), dict):
        raise RuntimeError('Health did not return a JSON object')
    app = get(primary, '/app/')
    require(app[0] == 200 and 'text/html' in app[1].get('content-type', ''), primary, '/app/', app)
    scripts = re.findall(r'<script\b[^>]*\bsrc=[\"\']([^\"\']+)', app[2].decode('utf-8', 'replace'), re.I)
    assets = [urlsplit(v).path for v in scripts if urlsplit(v).path.startswith('/app/assets/') and urlsplit(v).netloc in ('', primary)]
    if not assets:
        raise RuntimeError('Mini App HTML has no application script under /app/assets/')
    asset = get(primary, assets[0])
    require(asset[0] == 200 and ('javascript' in asset[1].get('content-type', '') or 'ecmascript' in asset[1].get('content-type', '')), primary, assets[0], asset)
    path = '/app/?tgWebAppStartParam=compatibility-check&source=old-link'
    for alias in aliases:
        for secure in (False, True):
            result = get(alias, path, secure)
            require(result[0] in (301, 308) and result[1].get('location') == 'https://' + primary + path, alias, path, result)
        print(f'OK legacy {alias} -> {primary} (HTTP + HTTPS, path + query)')
    print(f'OK {primary}: API JSON, storefront HTML and application asset; TLS=' + ('verified' if args.external or args.ca_file else 'loopback bootstrap probe'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', default='../.env')
    parser.add_argument('--external', action='store_true')
    parser.add_argument('--address', default='127.0.0.1')
    parser.add_argument('--http-port', type=int, default=80)
    parser.add_argument('--https-port', type=int, default=443)
    parser.add_argument('--ca-file')
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
        print(f'FAIL public routes: {exc}', file=sys.stderr)
        sys.exit(1)
